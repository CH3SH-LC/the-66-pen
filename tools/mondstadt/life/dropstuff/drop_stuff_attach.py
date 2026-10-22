"""对象③ revision 7：DropStuff(37) 的**完整原生通道**（CLI/schema + 固定 hook/probe/wrapper + raw accept）。

上一版只到「一个可编译的 .lib + 一个 ``Dispatch()`` 函数」，**未闭合**。本版交付的是**可用工具链**：

* **CLI 两个子命令，都真能跑**：
  ``--prepare``（每次生成的**一次性候选目录**：隔离 source copy + 固定 hook/probe/wrapper + target_config + schema）
  与 ``--compile-check``（用 MSVC 真编译 + 跑 layout probe + 跑 wrapper 的 dry 通道产出 **raw 日志**，
  再用**独立 decoder** 解码/接受）。
* **固定 hook / probe / wrapper**：三类源码是**固定的生成文本**（不是每次现编的临时拼装）。
* **raw 日志独立 decode/accept**：``decode_raw_receipt()`` / ``accept_raw_log()`` 与写侧**独立**，
  且**不硬编码布局** —— 偏移量取自编译产物 ``dropstuff_receipt_layout`` 的输出。
* **真实配置采集**（不只是挂空组件）：probe 能把组件的 **config message 原始字节成段 dump**；
  ``config_collection_plan()`` 给出采集清单（含唯一 DropGather(36) 样本 10007002）；
  写侧 ``ConfigWritePlan`` 有 ``measured-census / collected-from-template / caller-supplied`` 三种来源，
  kind 37 **无样本时具名拒绝**（``config_field_unknown``），**而不是静默挂空组件**。
* **G5 真实调用链（本版核心）**：``--chain-check`` 读**磁盘上的 raw 回执** + fixture verdict + TU 源码，
  逐项核对回执字节确由 ``NdsKind4EnsureAttachedEntry → EnsureKind4AttachedProduction（noinline）
  → AttachKind4Production → SerializeBeforeAfter`` 产出：``newKind4.wrapper`` 必须等于 **attach 返回值**
  且真出现在 ``afterRows``（``wrapperInAfter=true``），旧组件逐个 ``present=true``，
  ``countAfter == countBefore + 1``、``captureCodeBefore/After == 0``。
  **破坏生产调用后回执必须为空/缺失**（负控判据；fixture 不得自调序列化器）。
  ``--chain-sites`` / ``RAW_SERIALIZATION_CALL_MISSING`` 只是**补充**的源码接线检查，
  **不得以「grep 到调用」当接通**。

只读复用（允许读/include/link，**不改**）
----------------------------------------
* 只读层：``tools/game-executor/template-authoring/component_attachment.{h,cpp}``（隔离 source copy 后编译；
  原文件不动）—— ``CaptureComponents`` 独立读 HashSet/List 并复核身份/回指。
* 目标与身份：``tools/game-executor/native_profiles.py`` 的 ``TARGET_IMAGE`` / ``load_profile`` /
  ``inspect_pe`` / ``query_identity``。**原生目标 = ``YuanShen.exe``**；旧版 profile 写
  ``BeyondEditor.dll`` 且没有进程适配，本版修掉。
* 管线形状复用 ``tools/game-executor/native-options/build_generalized.py``（**该文件一行不改**）：
  隔离 source copy、``target_config``、编译 layout probe、nonce + deadline + hotfix 守卫、独立 readback。

常量（已定，照用）
------------------
``ACTION_CODE = 20`` · ``RECEIPT_VERSION = 25`` ·
source-run 根 ``.runtime/mondstadt-native/dropstuff/prepared/`` · kind 字符串 ``mondstadt-dropstuff-build-v1``。

边界
----
开发期**所有游戏派发关闭**：任何路径都不发原生请求、不注入进程、不写游戏内存；
开发期**不执行**真实派发（不是产品永久禁用）：wrapper 的真实通道由**分支**决定——进程身份 ==
``HR_TARGET_PID``、``OpenProcess`` 成功、目标镜像 == ``YuanShen.exe`` 三者齐备才派发，任一不满足即按各自
具名码拒绝（``HOOK_NOT_IN_TARGET_PROCESS`` / ``TARGET_PROCESS_NOT_OPEN`` / ``TARGET_IMAGE_MISMATCH``）；
``--compile-check`` 只编译/跑 dry 通道。wrapper 调用一旦开始，``executed=true`` 不得降级。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

__all__ = [
    "ACTION_CODE",
    "ATTACH_ABI",
    "COMPONENT_KINDS",
    "DICT_LIMIT",
    "DICT_SCALAR_TAGS",
    "DROPGATHER_SAMPLE",
    "EXECUTABLE_KINDS",
    "KIND_DROP_STUFF",
    "KIND_RUN_LEDGER",
    "KIND_STRING",
    "PREPARED_ROOT",
    "RAW_MARKER",
    "RAW_RECEIPT_FIELDS",
    "READ_LAYER",
    "RECEIPT_VERSION",
    "REQUIRED_LAYOUT_KEYS",
    "TOOLCHAIN",
    "AttachSpecError",
    "BuildAnchors",
    "ComponentRow",
    "DictRuntimePlan",
    "accept_raw_log",
    "attach_verdicts",
    "build_target_config",
    "chain_selfcheck",
    "compile_check",
    "config_collection_plan",
    "config_field_for_kind",
    "decode_component_row",
    "decode_raw_receipt",
    "dict_runtime_plan",
    "emit_toolchain_files",
    "native_profile",
    "plan_attach_batches",
    "prepare_candidate_dir",
    "production_chain_sites",
    "raw_receipt_chain_check",
    "receipt",
    "require_executable_kind",
    "verify_attach_receipt",
    "verify_dict_recipe_facts",
]

# ---------------------------------------------------------------------------
# 0. 常量（照用 owner 已定的值）
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
RECIPES_PATH = REPO_ROOT / "data" / "node-workbench" / "recipes.json"
PREFAB_DIR = (REPO_ROOT / ".runtime" / "mondstadt" / "rework-20261017" / "shared-source"
              / "official-prefab")
SHARED_NATIVE = REPO_ROOT / "tools" / "game-executor" / "template-authoring"
SHARED_NATIVE_EXTRA = REPO_ROOT / "tools" / "game-executor" / "native"
NATIVE_PROFILES = REPO_ROOT / "tools" / "game-executor" / "native_profiles.py"
BUILD_GENERALIZED = REPO_ROOT / "tools" / "game-executor" / "native-options" / "build_generalized.py"

ACTION_CODE = 20
RECEIPT_VERSION = 25
KIND_STRING = "mondstadt-dropstuff-build-v1"
PREPARED_ROOT = Path(".runtime/mondstadt-native/dropstuff/prepared")

TOOLCHAIN: dict = {
    "actionCode": ACTION_CODE,
    "receiptProtocol": RECEIPT_VERSION,
    "kindString": KIND_STRING,
    "preparedRoot": PREPARED_ROOT.as_posix(),
    "targetImageSource": "tools/game-executor/native_profiles.py:TARGET_IMAGE (YuanShen.exe)",
    "reusedPipelinePatterns": [
        "isolated-source-copy", "target-config", "compiled-layout-probe",
        "identity-nonce-deadline-hotfix-guards", "independent-readback",
    ],
    "pipelinePatternSource": ("tools/game-executor/native-options/build_generalized.py"
                              "（只读复用，不修改）"),
    "cli": {"prepare": "--prepare", "compileCheck": "--compile-check"},
    "gameDispatch": False,
}

COMPONENT_KINDS: dict[str, int] = {
    "BeyondCompTypeNone": 0, "BeyondCompTypeCustomValue": 1, "BeyondCompTypeTimer": 3,
    "BeyondCompTypeMover": 4, "BeyondCompTypeClientTrigger": 5, "BeyondCompTypeEffect": 6,
    "BeyondCompTypeBornPoint": 7, "BeyondCompTypeCollision": 8, "BeyondCompTypeFollowMove": 9,
    "BeyondCompTypeBulletMove": 11, "BeyondCompTypeHitDetection": 12, "BeyondCompTypeCamera": 13,
    "BeyondCompTypeRoleStatus": 14, "BeyondCompTypeAvatarDisturber": 15, "BeyondCompTypeCountDown": 16,
    "BeyondCompTypeOption": 17, "BeyondCompTypeCombat": 18, "BeyondCompTypeHitbox": 19,
    "BeyondCompTypeBulletPattern": 20, "BeyondCompTypeTempAttachPoint": 21,
    "BeyondCompTypeCustomSkill": 22, "BeyondCompTypeIntee": 23, "BeyondCompTypeMpAction": 24,
    "BeyondCompTypeTag": 25, "BeyondCompTypeEnmity": 26, "BeyondCompTypeNameplate": 27,
    "BeyondCompTypeTalk": 28, "BeyondCompTypeSoundEffect": 29, "BeyondCompTypeMonsterPatrol": 30,
    "BeyondCompTypeLevelStateMachine": 31, "BeyondCompTypeMinimapMark": 32,
    "BeyondCompTypeStuffBag": 33, "BeyondCompTypeEquipStuffBag": 34, "BeyondCompTypeShop": 35,
    "BeyondCompTypeDropGather": 36, "BeyondCompTypeDropStuff": 37, "BeyondCompTypeLightGroup": 38,
    "BeyondCompTypeScanEntity": 39, "BeyondCompTypePopUp": 40, "BeyondCompTypeObstacle": 41,
    "BeyondCompTypeMonsterAiComp": 42, "BeyondCompTypeWaterfallComp": 43,
    "BeyondCompTypeWaterCubeComp": 44, "BeyondCompTypeCursorCollision": 45,
    "BeyondCompTypeVehicle": 46, "BeyondCompTypeArraysize": 47,
}

KIND_DROP_STUFF = 37
KIND_DROP_GATHER = 36
#: **本模块私有分支：runtimeComponentKind=4（Mover）**。共享 `EnsureComponentAttached` 的
#: `{17,33,35}` 白名单**不改**；证据：`.runtime/mondstadt/rework-20261017/root-component-callpath/`
#: `…factory-ed2967/result.json`（owner attach `0x867c610` edx=kind → factory `0x13dddca0` ecx=kind →
#: switch `0x13dde4e4` 索引=kind−1 → kind4 block `0x13dddd28`；class 32589 `NGNFGANNPGG`、
#: type 427805、usage `0x2a925`、slot `0x57b0030`）。
KIND_DROP_MOVER = 4
EXECUTABLE_KINDS: tuple[int, ...] = (KIND_DROP_STUFF, KIND_DROP_MOVER)
KIND_RUN_LEDGER: dict[int, dict] = {
    KIND_DROP_STUFF: {"allowedToDispatch": True, "hasBeenRun": False, "runEvidence": None,
                      "why": "开发期所有游戏派发关闭；需统一阶段由 root 用 wrapper 的真实通道跑一次"},
    KIND_DROP_MOVER: {"allowedToDispatch": True, "hasBeenRun": False, "runEvidence": None,
                      "why": "kind4 走模块私有分支（共享白名单 17/33/35 不改）；开发期派发关闭，"
                             "统一阶段由 root 用 wrapper 真实通道跑一次；config 字段号未实测 ⇒ "
                             "会以 config_field_unknown 具名拒绝"},
}

READ_LAYER: dict = {
    "header": "tools/game-executor/template-authoring/component_attachment.h",
    "source": "tools/game-executor/template-authoring/component_attachment.cpp",
    "symbol": "ge::component_attachment::CaptureComponents",
    "reuseMode": "isolated-source-copy（复制进一次性目录后编译；原文件只读，不改）",
}

ATTACH_ABI: dict = {
    "callingConvention": "__cdecl",
    "signature": "void* (__cdecl*)(void* owner, std::int32_t kind)",
    "parameterCount": 2,
    "rvaSymbol": "DS_ATTACH_RVA",
    "rva": "0x867c610",
    "provenance": ("tools/game-executor/template-authoring/component_attachment.h:7 "
                   "(using AttachComponent = void* (__cdecl *)(void* owner, std::int32_t kind); // 867c610)"),
    "whitelistOfSharedPrimitive": [17, 33, 35],
    "whitelistPolicy": "共享 EnsureComponentAttached 的 {17,33,35} 保持原样；kind 37 走独立分支并强制身份相等",
}

MEASURED_PREFAB_ROW_CONFIG_FIELDS: dict[int, int] = {
    1: 11, 3: 13, 6: 16, 11: 21, 12: 22, 14: 24, 18: 28, 19: 29, 20: 30, 26: 37, 36: 47,
}
MEASURED_TEMPLATE_BLOCK_PAYLOAD_FIELDS: dict[int, int] = {
    1: 11, 8: 16, 9: 17, 10: 18, 11: 19, 12: 20, 24: 33, 25: 34, 26: 35, 27: 36,
    42: 55, 43: 51, 48: 58, 51: 61, 70: 75, 101: 90, 102: 91,
}

DICT_CONTAINER_STORAGE = 10003
DICT_ENTRY_STORAGE = 10007
DICT_LIMIT = 64
DICT_SCALAR_TAGS = ("int", "uint", "bool", "float", "string")
BUILD_DICT_NODE = 1088
ASSEMBLE_DICT_NODE = 1788
DICT_SINK_NODES = {725: (1, "战利品掉落字典"), 720: (1, "道具掉落字典")}

DROPGATHER_SAMPLE = {"registryId": 10007002, "nameZh": "挑战币掉落物",
                     "prefabFile": "14968727460853214978.mihoyobin.json", "kind": KIND_DROP_GATHER,
                     "configFieldObserved": 47}


class AttachSpecError(ValueError):
    """具名拒绝。每条都带 ``code``。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        return {"ok": False, "code": self.code, "detail": self.detail}


_REVERSE_KINDS = {value: name for name, value in COMPONENT_KINDS.items()}


def component_kind_name(kind: int) -> str:
    return _REVERSE_KINDS.get(int(kind), f"kind-{int(kind)}")


def require_executable_kind(kind: int) -> int:
    kind = int(kind)
    if kind not in EXECUTABLE_KINDS:
        raise AttachSpecError(
            "kind_not_in_executable_set",
            f"kind {kind}（{component_kind_name(kind)}）不在本模块可执行集合 {list(EXECUTABLE_KINDS)}；"
            f"枚举宽度 ≠ 支持。已真跑过的 kind："
            f"{sorted(k for k, v in KIND_RUN_LEDGER.items() if v['hasBeenRun'])}",
        )
    return kind


def config_field_for_kind(kind: int) -> int:
    kind = require_executable_kind(kind)
    if kind == KIND_DROP_MOVER:
        # **kind4 私有分支**：config 字段号未实测 ⇒ **具名拒绝**（不猜、不静默挂空组件）。
        raise AttachSpecError(
            "config_field_unknown",
            f"kind {kind}（KIND_DROP_MOVER，Mover）在预制行普查里没有实测 config 字段号"
            f"（已测 {sorted(MEASURED_PREFAB_ROW_CONFIG_FIELDS)}）；"
            "只有名字/枚举/静态链证据时不许外推 ⇒ 按 config_field_unknown 拒绝",
        )
    try:
        return MEASURED_PREFAB_ROW_CONFIG_FIELDS[kind]
    except KeyError:
        raise AttachSpecError(
            "config_field_unknown",
            f"kind {kind} 在预制行普查里没有实测 config 字段号（已测 "
            f"{sorted(MEASURED_PREFAB_ROW_CONFIG_FIELDS)}）；只有名字/枚举证据时不许外推"
            "（world-contract v26 componentConfigFieldIsNotArithmetic）。改用 config_collection_plan()",
        ) from None


# ---------------------------------------------------------------------------
# 1. 组件行编解码（行层真代码）
# ---------------------------------------------------------------------------

WIRE_VARINT = 0
WIRE_LENGTH = 2
COMPONENT_ROW_FIELDS = {"kind": 1, "enabled": 2}


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise AttachSpecError("negative_varint", f"varint 不接受负数：{value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise AttachSpecError("truncated_varint", "varint 越界")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise AttachSpecError("varint_too_long", "varint 超过 10 字节")


@dataclass(frozen=True)
class ComponentRow:
    kind: int
    enabled: bool = True
    config_field: int | None = None
    config_bytes: bytes = b""

    def __post_init__(self) -> None:
        require_executable_kind(self.kind)
        if self.config_field is None and self.config_bytes:
            raise AttachSpecError("config_bytes_without_field", "给了 config_bytes 就必须给 config_field")
        if self.config_field is not None and self.config_field < 1:
            raise AttachSpecError("config_field_not_positive", f"config_field 必须 ≥1：{self.config_field}")

    def encode(self) -> bytes:
        out = bytearray()
        out += _encode_varint(COMPONENT_ROW_FIELDS["kind"] << 3 | WIRE_VARINT)
        out += _encode_varint(int(self.kind))
        out += _encode_varint(COMPONENT_ROW_FIELDS["enabled"] << 3 | WIRE_VARINT)
        out += _encode_varint(1 if self.enabled else 0)
        if self.config_field is not None:
            out += _encode_varint(self.config_field << 3 | WIRE_LENGTH)
            out += _encode_varint(len(self.config_bytes)) + bytes(self.config_bytes)
        return bytes(out)


def decode_component_row(buf: bytes) -> ComponentRow:
    pos = 0
    kind: int | None = None
    enabled = True
    cfg_field: int | None = None
    cfg_bytes = b""
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == WIRE_VARINT:
            value, pos = _read_varint(buf, pos)
            if number == COMPONENT_ROW_FIELDS["kind"]:
                kind = value
            elif number == COMPONENT_ROW_FIELDS["enabled"]:
                enabled = bool(value)
            else:
                raise AttachSpecError("unknown_row_varint_field", f"行内不认识的 varint 字段 {number}")
        elif wire == WIRE_LENGTH:
            size, pos = _read_varint(buf, pos)
            data = buf[pos:pos + size]
            if len(data) != size:
                raise AttachSpecError("truncated_row_field", f"字段 {number} 声明 {size} 字节，实际不足")
            pos += size
            cfg_field, cfg_bytes = number, data
        else:
            raise AttachSpecError("unsupported_wire_type", f"字段 {number} 的 wire 类型 {wire} 不支持")
    if kind is None:
        raise AttachSpecError("row_missing_kind", "行里没有 f1（kind）")
    return ComponentRow(kind=kind, enabled=enabled, config_field=cfg_field, config_bytes=cfg_bytes)


def row_roundtrip_selftest() -> dict:
    cases = (ComponentRow(kind=KIND_DROP_STUFF),
             ComponentRow(kind=KIND_DROP_STUFF, enabled=False),
             ComponentRow(kind=KIND_DROP_STUFF, config_field=47, config_bytes=b"\x08\x01"))
    for row in cases:
        if decode_component_row(row.encode()) != row:
            raise AttachSpecError("row_roundtrip_mismatch", f"{row} 往返不一致")
    return {"ok": True, "cases": len(cases), "hexes": [r.encode().hex() for r in cases]}


# ---------------------------------------------------------------------------
# 2. 纪律守卫（raw 侧同款纪律在 C++ 里）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildAnchors:
    build_sha256: str
    derived_utc: str
    anchors: dict = field(default_factory=dict)

    def require(self, name: str) -> int:
        if name not in self.anchors:
            raise AttachSpecError("ABI_ANCHOR_NOT_DERIVED",
                                  f"锚 {name!r} 在 build {self.build_sha256[:12]} 上没有推导记录")
        return int(self.anchors[name])


@dataclass(frozen=True)
class AttachRequest:
    entity_ref: str
    entity_id: int
    kind: int = KIND_DROP_STUFF

    def __post_init__(self) -> None:
        require_executable_kind(self.kind)
        if not 1 <= int(self.entity_id) <= 4294967295:
            raise AttachSpecError("host_out_of_uint32", f"实体 id {self.entity_id} 不在 uint32 范围")


def plan_attach_batches(requests: Sequence[AttachRequest], *, max_per_batch: int = 1) -> dict:
    if max_per_batch < 1:
        raise AttachSpecError("bad_batch_size", "max_per_batch 必须 ≥1")
    seen: dict[int, int] = {}
    for req in requests:
        seen[req.entity_id] = seen.get(req.entity_id, 0) + 1
    duplicated = sorted(eid for eid, count in seen.items() if count > 1)
    if duplicated and max_per_batch > 1:
        raise AttachSpecError(
            "DROPSTUFF_HOSTS_SHARE_ENTITY_NEED_NATIVE_BASELINE",
            f"宿主 {duplicated} 在多批里重复出现；多批写同一实体不得沿用同一份 before 基线")
    batches = [{"batchIndex": i // max_per_batch,
                "hosts": [{"ref": r.entity_ref, "entityId": r.entity_id, "kind": r.kind}
                          for r in requests[i:i + max_per_batch]],
                "needsFreshBaseline": True} for i in range(0, len(requests), max_per_batch)]
    return {"ok": True, "requestCount": len(requests), "batchCount": len(batches),
            "duplicateHosts": duplicated, "batches": batches}


def verify_attach_receipt(receipt_doc: dict) -> dict:
    before_src = receipt_doc.get("beforeSource")
    after_src = receipt_doc.get("afterSource")
    if not before_src or not after_src:
        raise AttachSpecError("SYNC_PROOF_INCOMPLETE", "回执必须带 beforeSource 与 afterSource")
    if before_src == after_src:
        raise AttachSpecError("SYNC_PROOF_SAME_SOURCE_NOT_ACCEPTED",
                              "同一来源前后比永远相等，检测不到未保存的原生改动")
    diff = receipt_doc.get("diff") or {}
    if "addedRows" not in diff or "changedRows" not in diff:
        raise AttachSpecError("SYNC_PROOF_NO_FIELD_DIFF", "差分必须逐行逐字段")
    expected = receipt_doc.get("expectedKind")
    added_kinds = [row.get("kind") for row in diff.get("addedRows") or []]
    if expected is not None and added_kinds != [expected]:
        raise AttachSpecError("SYNC_PROOF_UNEXPECTED_DELTA",
                              f"期望恰好新增 kind={expected}，实测 {added_kinds}")
    return {"ok": True, "code": "SYNC_PROOF_ACCEPTED", "addedKinds": added_kinds}


# ---------------------------------------------------------------------------
# 3. target_config（原生目标 = YuanShen.exe；只读复用 native_profiles）
# ---------------------------------------------------------------------------


def _load_native_profiles():
    sys.path.insert(0, str(REPO_ROOT / "tools" / "game-executor"))
    try:
        import native_profiles  # type: ignore
    except Exception as error:  # pragma: no cover
        raise AttachSpecError("native_profiles_import_failed",
                              f"{NATIVE_PROFILES} 无法导入：{type(error).__name__}: {error}") from None
    return native_profiles


def build_target_config() -> dict:
    """原生目标档：**YuanShen.exe**（不是 BeyondEditor.dll）+ 只读磁盘校验 + per-run 守卫参数。"""
    out: dict = {
        "kindString": kind_string_for(_ACTIVE_KIND), "actionCode": ACTION_CODE, "receiptProtocol": RECEIPT_VERSION,
        "attachAbi": dict(ATTACH_ABI), "readLayer": dict(READ_LAYER),
        "executableKinds": list(EXECUTABLE_KINDS), "refusals": [],
        "profileVerified": False, "imageObserved": None, "targetImage": None,
    }
    try:
        profiles = _load_native_profiles()
    except AttachSpecError as error:
        out["refusals"].append(error.as_dict())
        return out
    target = Path(profiles.TARGET_IMAGE)
    out["targetImage"] = str(target)
    out["targetImageExists"] = target.is_file()
    out["targetImageBytes"] = target.stat().st_size if target.is_file() else None
    try:
        out["imageObserved"] = profiles.verify_disk(profiles.load_profile())
        out["profileVerified"] = True
    except Exception as error:
        out["refusals"].append({"code": "PROFILE_VERIFY_REFUSED",
                                "detail": f"{type(error).__name__}: {error}"})
    try:
        profiles.require_action(profiles.load_profile(), str(ACTION_CODE))
        out["actionRegisteredInProfile"] = True
    except Exception as error:
        out["actionRegisteredInProfile"] = False
        out["refusals"].append({"code": "ACTION_NOT_REGISTERED_IN_PROFILE",
                                "detail": f"action {ACTION_CODE}: {type(error).__name__}: {error}"})
    out["hotfixRvas"] = _hotfix_rvas()
    out["deadlineNow"] = _uptime_ms()
    return out


def _hotfix_rvas() -> list[str]:
    """从 native_profiles 的 profile 里读 hotfix 字节 RVA（只读；缺失就给空表）。

    该字段的形状在不同 profile 版本里出现过两种（字符串列表 / 带 ``rva`` 的字典列表），
    这里两种都接受并统一成字符串列表 —— 不为一个只读字段假设形状。
    """
    try:
        profiles = _load_native_profiles()
        profile = profiles.load_profile()
    except Exception:
        return []
    out: list[str] = []
    for row in profile.get("defaultHotfixByteRvas", []):
        if isinstance(row, dict):
            out.append(str(row.get("rva")))
        else:
            out.append(str(row))
    return out


def _uptime_ms() -> int:
    """进程/系统 uptime（毫秒）。用于 deadline：``GetTickCount64() + ttl``。"""
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetTickCount64())
    except Exception:  # pragma: no cover
        return 0


# ---------------------------------------------------------------------------
# 4. 一次性候选目录 + 固定 hook/probe/wrapper
# ---------------------------------------------------------------------------

_TARGET_CONFIG_H = """// 由 drop_stuff_attach.py 生成（一次性候选目录）—— 请勿手改。
#pragma once
#define DS_ACTION_CODE @@ACTION@@
#define DS_RECEIPT_VERSION @@PROTOCOL@@
#define DS_KIND @@KIND@@
#define DS_KIND_STRING "@@KINDSTRING@@"
#define DS_ATTACH_RVA @@ATTACHRVA@@ull
#define DS_NONCE @@NONCE@@ull
#define DS_DEADLINE_TICK @@DEADLINE@@ull
#define DS_HOST_LIMIT 4
#define HR_ACTION @@ACTION@@
#define HR_NONCE @@NONCE@@ull
#define HR_DEADLINE @@DEADLINE@@ull
#define HR_TARGET_PID @@PID@@ull
#define HR_TARGET_TID @@TID@@ull
#define HR_TARGET_CREATION @@CREATION@@ull
#define HR_TARGET_THREAD_CREATION @@THREADCREATION@@ull
#define HR_TARGET_IMAGE L"@@IMAGE@@"
// ---- 共享 emitter (build_readonly_profile.py:50-80 emit_header) 的同源常量，照抄其 values ----
// HR_READ_CONTEXT / GS_BOOTSTRAP_READONLY：该 emitter 的 values 里**无条件为 1**（无 if 条件）。
#ifndef HR_READ_CONTEXT
#define HR_READ_CONTEXT 1
#endif
// action 卡专属常量（照 action 卡 emitter build_scene_profile.py:262-281）：
// GS_BOOTSTRAP_READONLY **=0**（只读引导与 action 互斥，见 game_context_snapshot.h:52 的 #error）
#define GS_BOOTSTRAP_READONLY 0
#define HR_EXPECTED_LEVEL 1073741843ULL
// 锚点：照 build_readonly_profile.py:71-72 的形式由 profile.anchors[*].bytes 生成（32 B 字节表）。
// **与 game_scene_action.cpp:35-38 自带的 HR_LEVEL_ANCHOR_RVA / HR_PLACE_ANCHOR_RVA 严格区分**（那些带 _RVA）。
#define HR_LEVEL_ANCHOR @@LEVELANCHOR@@
#define HR_PLACE_ANCHOR @@PLACEANCHOR@@
#define HR_SAVE_ANCHOR @@SAVEANCHOR@@
// HR_EXPECTED_ENTITY_IDS：**数组定义**（照 build_scene_profile.py:309 的同一形式：
// `[[maybe_unused]] static constexpr unsigned int HR_EXPECTED_ENTITY_IDS[] = {…};`）。
// 真实值属调用方 baseline/review 输入；给出时用其真实 ID 列表，未给出时用**显式 compile-only fixture** `0`
// 并让卡片 launchable=false + 具名码（**不编任何真实 ID**）。
[[maybe_unused]] static constexpr unsigned int HR_EXPECTED_ENTITY_IDS[] = {@@ENTITYIDS@@};
// HR_MAPPING：同源规则 = 字面前缀 "Local\\Miliastra.Readonly." + 16 字节 hex；
// 这里用已替换的 @@NONCE@@（64 位 ⇒ 恰好 16 个 hex 字符）承载那个 hex 段。
// 共享 emit_header 对**字符串值**一律发宽字面量（源码：`literal='L'+json.dumps(value) if isinstance(value,str) else …`）
// ⇒ 共享 hook 走 OpenFileMappingW / 宽比较，这里必须 L"..."（否则 C2664 char[]→LPCWSTR）。
#define HR_MAPPING L"Local\\\\Miliastra.Scene.Fixed.@@NONCE@@"
// HR_MESSAGE_ID：共享 emitter 里是**调用方入参**（本模块无法从共享侧取得真值）。
// 未由 route 给出时按 0 写出并**不声称可派发**（卡片 launchable=false + 具名码
// HR_MESSAGE_ID_REQUIRED_FROM_ROUTE）；给出真值时才可绑定 —— 不编数字换绿。
#define HR_MESSAGE_ID @@MESSAGEID@@
// 同源写法（build_scene_profile.py:265-266 / build_readonly_profile.py:55-56）：DLL 路径与 attempt 文件。
// 注意：本模板是**非 raw** Python 字符串 ⇒ 反斜杠要写成四份，生成到 C++ 才是 `\\`（同 HR_MAPPING 的坑）。
#define HR_DLL_PATH L"@@RUN@@\\\\hook_receipt.dll"
#define HR_ATTEMPT_FILE L"@@RUN@@\\\\attempt.used"
"""

_H_KIND37 = r"""// 固定 hook 头（drop_stuff_attach.py 生成）—— kind-37 独立分支，不用共享白名单。
#pragma once
#include "component_attachment.h"
#include "dropstuff_target_config.h"
#include <cstdint>

namespace dropstuff {

constexpr std::int32_t kKindDropStuff = DS_KIND;
constexpr std::uint32_t kMaxHosts = DS_HOST_LIMIT;

using AttachComponentFn = void* (__cdecl*)(void* owner, std::int32_t kind);
using ReadSource = ge::templates::TemplateReadSource;
using WriteBytesFn = bool (*)(void* context, std::uint64_t address, const void* bytes, std::size_t size);

// config 写入计划：字段来源必须具名（不许猜）。
enum class ConfigFieldSource : std::uint32_t {
    none = 0, measuredCensus = 1, collectedFromTemplate = 2, callerSupplied = 3
};

struct ConfigWritePlan {
    bool hasConfig;
    std::int32_t field;
    ConfigFieldSource fieldSource;
    const void* bytes;
    std::size_t size;
    void* writerContext;
};

enum class Code : std::uint32_t {
    ok = 0, existing = 1, kind_not_in_executable_set = 2, before_failed = 3, attach_missing = 4,
    after_failed = 5, delta_mismatch = 6, prefix_changed = 7, kind_mismatch = 8,
    wrapper_identity_mismatch = 9, null_return = 10, capture_limit = 11,
    raw_accept_missing = 12, raw_accept_wrapper_mismatch = 13, raw_accept_same_source_proof = 14,
    host_limit_exceeded = 15, config_field_unknown = 16, config_write_failed = 17,
};

const char* CodeName(Code code);
bool IsExecutableKind(std::int32_t kind);

struct Result {
    Code code;
    std::uint64_t wrapper;
    std::uint32_t before_count;
    std::uint32_t after_count;
    bool attach_called;
    std::int32_t configField;
    bool configWritten;
};

Result EnsureDropStuffAttached(ReadSource source, AttachComponentFn attach, std::uint64_t owner,
                               ge::component_attachment::AttachmentWorkspace* work,
                               const ConfigWritePlan* plan, WriteBytesFn writer);

struct LedgerLine {
    std::uint64_t owner, wrapper, config;
    std::int32_t kind;
    std::uint8_t enabled;
    bool independentReadback;
    const char* sourceOfBaseline;
    const char* sourceOfAfter;
};

Code RawAccept(ReadSource source, std::uint64_t owner, std::uint64_t expectedWrapper,
               ge::component_attachment::CaptureWorkspace* work, LedgerLine* out);

// 采集用：把一个组件的 config message 头段原始字节读出来（只读；给 DropGather 样本与未来 37 样本）
struct ConfigDump {
    std::uint64_t owner, wrapper, config;
    std::int32_t kind;
    std::uint32_t size;
    std::uint8_t bytes[64];
};

Code DumpRowConfig(ReadSource source, std::uint64_t owner, std::int32_t kind,
                   ge::component_attachment::CaptureWorkspace* work, ConfigDump* out);

}  // namespace dropstuff
"""

_CPP_KIND37 = r"""// 固定 hook 实现（drop_stuff_attach.py 生成）
#include "dropstuff_kind37.h"
#include <cstring>

namespace dropstuff {
namespace ca = ge::component_attachment;

const char* CodeName(Code code) {
    switch (code) {
    case Code::ok: return "ok";
    case Code::existing: return "existing";
    case Code::kind_not_in_executable_set: return "kind_not_in_executable_set";
    case Code::before_failed: return "before_failed";
    case Code::attach_missing: return "attach_missing";
    case Code::after_failed: return "after_failed";
    case Code::delta_mismatch: return "delta_mismatch";
    case Code::prefix_changed: return "prefix_changed";
    case Code::kind_mismatch: return "kind_mismatch";
    case Code::wrapper_identity_mismatch: return "wrapper_identity_mismatch";
    case Code::null_return: return "null_return";
    case Code::capture_limit: return "capture_limit";
    case Code::raw_accept_missing: return "raw_accept_missing";
    case Code::raw_accept_wrapper_mismatch: return "raw_accept_wrapper_mismatch";
    case Code::raw_accept_same_source_proof: return "raw_accept_same_source_proof";
    case Code::host_limit_exceeded: return "host_limit_exceeded";
    case Code::config_field_unknown: return "config_field_unknown";
    case Code::config_write_failed: return "config_write_failed";
    }
    return "unknown";
}

bool IsExecutableKind(std::int32_t kind) { return kind == DS_KIND || kind == 4; }

Result EnsureDropStuffAttached(ReadSource source, AttachComponentFn attach, std::uint64_t owner,
                               ca::AttachmentWorkspace* work, const ConfigWritePlan* plan,
                               WriteBytesFn writer) {
    Result out{};
    out.code = Code::attach_missing;
    if (!attach || !work || !source.read || owner == 0) { return out; }

    ca::CaptureComponents(source, owner, &work->capture, &work->before);
    out.before_count = work->before.count;
    if (work->before.code != ca::CaptureCode::complete) { out.code = Code::before_failed; return out; }

    for (std::uint32_t i = 0; i < work->before.count; ++i) {
        if (work->before.rows[i].kind != DS_KIND) { continue; }
        out.code = Code::existing;
        out.wrapper = work->before.rows[i].wrapper;
        out.after_count = work->before.count;
        return out;
    }
    if (work->before.count >= ca::kMaxComponents) { out.code = Code::capture_limit; return out; }

    void* returned = nullptr;
    try { returned = attach(reinterpret_cast<void*>(owner), DS_KIND); } catch (...) {
        out.code = Code::attach_missing; return out;
    }
    out.attach_called = true;

    ca::CaptureComponents(source, owner, &work->capture, &work->after);
    out.after_count = work->after.count;
    if (work->after.code != ca::CaptureCode::complete) { out.code = Code::after_failed; return out; }
    if (work->after.count != work->before.count + 1) { out.code = Code::delta_mismatch; return out; }
    for (std::uint32_t i = 0; i < work->before.count; ++i) {
        if (std::memcmp(&work->before.rows[i], &work->after.rows[i], sizeof(ca::ComponentRow)) != 0) {
            out.code = Code::prefix_changed; return out;
        }
    }
    const ca::ComponentRow& added = work->after.rows[work->before.count];
    if (added.kind != DS_KIND) { out.code = Code::kind_mismatch; return out; }
    if (returned == nullptr) { out.code = Code::null_return; return out; }
    if (reinterpret_cast<std::uint64_t>(returned) != added.wrapper) {
        out.code = Code::wrapper_identity_mismatch; return out;
    }
    out.wrapper = added.wrapper;

    // config：字段来源必须具名；kind 37 无实测字段 ⇒ 拒绝（不静默挂空组件）
    if (plan && plan->hasConfig) {
        if (plan->field <= 0 || plan->fieldSource == ConfigFieldSource::none) {
            out.code = Code::config_field_unknown;
            return out;
        }
        if (!writer || !plan->bytes || !plan->size) { out.code = Code::config_write_failed; return out; }
        if (!writer(plan->writerContext, added.config, plan->bytes, plan->size)) {
            out.code = Code::config_write_failed; return out;
        }
        out.configWritten = true;
        out.configField = plan->field;
    }
    out.code = Code::ok;
    return out;
}

Code RawAccept(ReadSource source, std::uint64_t owner, std::uint64_t expectedWrapper,
               ca::CaptureWorkspace* work, LedgerLine* out) {
    if (!out) { return Code::raw_accept_missing; }
    std::memset(out, 0, sizeof(*out));
    if (!work || !source.read || owner == 0) { return Code::raw_accept_missing; }
    ca::ComponentSnapshot fresh{};
    ca::CaptureComponents(source, owner, work, &fresh);
    if (fresh.code != ca::CaptureCode::complete) { return Code::before_failed; }
    for (std::uint32_t i = 0; i < fresh.count; ++i) {
        const ca::ComponentRow& row = fresh.rows[i];
        if (row.kind != DS_KIND) { continue; }
        if (expectedWrapper != 0 && row.wrapper != expectedWrapper) {
            return Code::raw_accept_wrapper_mismatch;
        }
        out->owner = owner; out->wrapper = row.wrapper; out->config = row.config;
        out->kind = row.kind; out->enabled = row.enabled;
        out->independentReadback = true;
        out->sourceOfBaseline = "hook::EnsureDropStuffAttached";
        out->sourceOfAfter = "probe::CaptureComponents";
        return Code::ok;
    }
    return Code::raw_accept_missing;
}

Code DumpRowConfig(ReadSource source, std::uint64_t owner, std::int32_t kind,
                   ca::CaptureWorkspace* work, ConfigDump* out) {
    if (!out || !work || !source.read || owner == 0) { return Code::raw_accept_missing; }
    std::memset(out, 0, sizeof(*out));
    ca::ComponentSnapshot fresh{};
    ca::CaptureComponents(source, owner, work, &fresh);
    if (fresh.code != ca::CaptureCode::complete) { return Code::before_failed; }
    for (std::uint32_t i = 0; i < fresh.count; ++i) {
        const ca::ComponentRow& row = fresh.rows[i];
        if (row.kind != kind) { continue; }
        out->owner = owner; out->wrapper = row.wrapper; out->config = row.config; out->kind = row.kind;
        if (!row.config) { return Code::ok; }
        if (!source.read(source.context, row.config, out->bytes, sizeof(out->bytes))) {
            return Code::config_write_failed;
        }
        out->size = static_cast<std::uint32_t>(sizeof(out->bytes));
        return Code::ok;
    }
    return Code::raw_accept_missing;
}

}  // namespace dropstuff
"""

_CPP_LAYOUT_PROBE = r"""// 编译期 layout probe（drop_stuff_attach.py 生成）—— verifier 绝不硬编码这些偏移。
#include "dropstuff_kind37.h"
#include <cstdio>
#include <cstddef>

namespace ds_layout {

// 组件行（与验收器固定词表同序）——行宽与各字段偏移**由编译器实测**，不再手写。
struct Row {
    std::int32_t kind;
    std::uint32_t entityId;
    std::uint64_t itemId;
    std::int32_t count;
    std::int32_t trigger;
};

// before/after 两张组件表（各留 4 行容量）——给 before/after 段偏移与 stride 提供实测来源。
struct ComponentsSection {
    Row before[4];
    Row after[4];
};

// kind37 config 头段（可探测部分）——与固定词表 (kind,entityId,itemId,count,trigger) 同序。
struct ConfigHead {
    std::int32_t kind;
    std::uint32_t entityId;
    std::uint64_t itemId;
    std::int32_t count;
    std::int32_t trigger;
};

}  // namespace ds_layout

int main() {
    std::printf("{");
    std::printf("\"action\":%d,", DS_ACTION_CODE);
    std::printf("\"protocol\":%d,", DS_RECEIPT_VERSION);
    std::printf("\"kind\":%d,", DS_KIND);
    std::printf("\"kindString\":\"%s\",", DS_KIND_STRING);
    std::printf("\"sizeof_Result\":%zu,", sizeof(dropstuff::Result));
    std::printf("\"offsetof_Result_code\":%zu,", offsetof(dropstuff::Result, code));
    std::printf("\"offsetof_Result_wrapper\":%zu,", offsetof(dropstuff::Result, wrapper));
    std::printf("\"offsetof_Result_before_count\":%zu,", offsetof(dropstuff::Result, before_count));
    std::printf("\"offsetof_Result_after_count\":%zu,", offsetof(dropstuff::Result, after_count));
    std::printf("\"offsetof_Result_attach_called\":%zu,", offsetof(dropstuff::Result, attach_called));
    std::printf("\"offsetof_Result_configField\":%zu,", offsetof(dropstuff::Result, configField));
    std::printf("\"offsetof_Result_configWritten\":%zu,", offsetof(dropstuff::Result, configWritten));
    std::printf("\"sizeof_ConfigWritePlan\":%zu,", sizeof(dropstuff::ConfigWritePlan));
    std::printf("\"offsetof_ConfigWritePlan_field\":%zu,", offsetof(dropstuff::ConfigWritePlan, field));
    std::printf("\"offsetof_ConfigWritePlan_fieldSource\":%zu,", offsetof(dropstuff::ConfigWritePlan, fieldSource));
    std::printf("\"sizeof_ConfigDump\":%zu,", sizeof(dropstuff::ConfigDump));
    std::printf("\"sizeof_LedgerLine\":%zu,", sizeof(dropstuff::LedgerLine));
    std::printf("\"configDumpBytes\":%zu,", sizeof(dropstuff::ConfigDump::bytes));
    std::printf("\"sizeof_Row\":%zu,", sizeof(ds_layout::Row));
    std::printf("\"offsetof_Row_kind\":%zu,", offsetof(ds_layout::Row, kind));
    std::printf("\"offsetof_Row_entityId\":%zu,", offsetof(ds_layout::Row, entityId));
    std::printf("\"offsetof_Row_itemId\":%zu,", offsetof(ds_layout::Row, itemId));
    std::printf("\"offsetof_Row_count\":%zu,", offsetof(ds_layout::Row, count));
    std::printf("\"offsetof_Row_trigger\":%zu,", offsetof(ds_layout::Row, trigger));
    std::printf("\"sizeof_ComponentsSection\":%zu,", sizeof(ds_layout::ComponentsSection));
    std::printf("\"offsetof_ComponentsSection_before\":%zu,",
                offsetof(ds_layout::ComponentsSection, before));
    std::printf("\"offsetof_ComponentsSection_after\":%zu,",
                offsetof(ds_layout::ComponentsSection, after));
    std::printf("\"sizeof_ConfigHead\":%zu,", sizeof(ds_layout::ConfigHead));
    std::printf("\"offsetof_ConfigHead_kind\":%zu,", offsetof(ds_layout::ConfigHead, kind));
    std::printf("\"offsetof_ConfigHead_entityId\":%zu,", offsetof(ds_layout::ConfigHead, entityId));
    std::printf("\"offsetof_ConfigHead_itemId\":%zu,", offsetof(ds_layout::ConfigHead, itemId));
    std::printf("\"offsetof_ConfigHead_count\":%zu,", offsetof(ds_layout::ConfigHead, count));
    std::printf("\"offsetof_ConfigHead_trigger\":%zu", offsetof(ds_layout::ConfigHead, trigger));
    std::printf("}\n");
    return 0;
}
"""

_CPP_WRAPPER = r"""// 固定 wrapper（drop_stuff_attach.py 生成）：守卫（目标镜像/nonce/deadline）+ 派发 + raw 日志。
// --dry 通道用内嵌模拟内存（离线编译/解码自检）；真实通道由**分支**决定是否执行：
// 进程身份 == HR_TARGET_PID、OpenProcess 成功、目标镜像 == YuanShen.exe 三者齐备才派发，
// 任一不满足即按各自的具名码拒绝（HOOK_NOT_IN_TARGET_PROCESS / TARGET_PROCESS_NOT_OPEN /
// TARGET_IMAGE_MISMATCH）—— 不是"永远禁用"。
#include "dropstuff_kind37.h"
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <cstdlib>

namespace ca = ge::component_attachment;
using namespace dropstuff;

// 真实通道用的只读源：进程句柄 + ReadProcessMemory（此前只在 probe 模板里定义，
// wrapper TU 缺 ⇒ `C2065 'ProcMem'/'ProcRead' undeclared`，rev26/27 真构建抓到）。
struct ProcMem { HANDLE process; };
static bool ProcRead(void* ctx, std::uint64_t address, void* target, std::size_t size) noexcept {
    ProcMem* mem = static_cast<ProcMem*>(ctx);
    SIZE_T done = 0;
    return mem && mem->process &&
           ReadProcessMemory(mem->process, reinterpret_cast<LPCVOID>(address), target, size,
                             &done) && done == size;
}

namespace sim {
constexpr std::uint64_t O = 0x100000, S = 0x110000, L = 0x120000, B = 0x130000,
                       SL = 0x140000, IT = 0x150000;
constexpr std::uint64_t OC = 0x800000, WC = 0x810000, DC = 0x820000, XC = 0x830000;
static unsigned char g_bytes[0x400000];
static unsigned g_calls = 0;
static bool g_wrong_return = false;
template<class T> void Put(std::uint64_t a, T v) { std::memcpy(g_bytes + (a - O), &v, sizeof(v)); }
template<class T> T Get(std::uint64_t a) { T v{}; std::memcpy(&v, g_bytes + (a - O), sizeof(v)); return v; }
bool Read(void* c, std::uint64_t a, void* t, std::size_t s) noexcept {
    (void)c;
    if (a < O || a - O > sizeof(g_bytes) || s > sizeof(g_bytes) - (std::size_t)(a - O)) { return false; }
    std::memcpy(t, g_bytes + (a - O), s); return true;
}
void AddSet(std::int32_t k) {
    const std::uint32_t i = Get<std::uint32_t>(S + 0x2c);
    const std::uint64_t cap = Get<std::uint64_t>(B + 0x18);
    const std::uint64_t bk = B + 0x20 + ((std::uint32_t)k % cap) * 4;
    const ca::NativeSetSlot slot{k, Get<std::int32_t>(bk) - 1, k};
    Put(SL + 0x20 + i * sizeof(slot), slot);
    Put<std::uint32_t>(bk, i + 1);
    Put<std::uint32_t>(S + 0x2c, i + 1);
    Put<std::uint32_t>(S + 0x28, Get<std::uint32_t>(S + 0x28) + 1);
    Put<std::uint32_t>(S + 0x34, Get<std::uint32_t>(S + 0x34) + 1);
}
std::uint64_t AddList(std::int32_t k) {
    const std::uint32_t i = Get<std::uint32_t>(L + 0x18);
    const std::uint64_t w = 0x160000 + i * 0x100, c = 0x180000 + i * 0x100;
    const std::uint64_t klass = (k == DS_KIND) ? DC : XC;
    Put<std::uint64_t>(w, WC); Put<std::uint64_t>(w + 0x20, O); Put<std::uint64_t>(w + 0x28, c);
    Put<std::uint8_t>(w + 0x30, 1); Put<std::int32_t>(w + 0x34, k);
    Put<std::uint64_t>(c, klass); Put<std::uint64_t>(c + 0x18, w); Put<std::uint64_t>(c + 0x20, O);
    Put<std::uint64_t>(IT + 0x20 + i * 8, w);
    Put<std::uint32_t>(L + 0x18, i + 1);
    Put<std::uint32_t>(L + 0x1c, Get<std::uint32_t>(L + 0x1c) + 1);
    return w;
}
void Add(std::int32_t k) { AddSet(k); (void)AddList(k); }
void Init() {
    std::memset(g_bytes, 0, sizeof(g_bytes));
    g_calls = 0;
    Put<std::uint64_t>(O, OC); Put<std::uint64_t>(O + 0x30, S); Put<std::uint64_t>(O + 0x68, L);
    Put<std::uint8_t>(O + 0x9c, 1);
    Put<std::uint64_t>(S, 0x840000ull); Put<std::uint64_t>(S + 0x10, B);
    Put<std::uint64_t>(S + 0x18, 0x850000ull); Put<std::uint64_t>(S + 0x20, SL);
    Put<std::int32_t>(S + 0x30, -1);
    Put<std::uint64_t>(L, 0x860000ull); Put<std::uint64_t>(L + 0x10, IT);
    Put<std::uint64_t>(B + 0x18, 7ull); Put<std::uint64_t>(SL + 0x18, 7ull);
    Put<std::uint64_t>(IT + 0x18, 7ull);
}
void* __cdecl Attach(void* v, std::int32_t k) {
    ++g_calls;
    if ((std::uint64_t)v != O || k != DS_KIND) { return nullptr; }
    AddSet(k);
    const std::uint64_t w = AddList(k);
    return (void*)(g_wrong_return ? w + 8 : w);
}
bool WriteBytes(void* c, std::uint64_t a, const void* bytes, std::size_t size) {
    (void)c;
    if (a < O || a - O > sizeof(g_bytes) || size > sizeof(g_bytes) - (std::size_t)(a - O)) { return false; }
    std::memcpy(g_bytes + (a - O), bytes, size); return true;
}
}  // namespace sim

static bool CurrentImageIsTarget(const char* expectedImage) {
    char path[MAX_PATH * 2]{};
    DWORD size = sizeof(path);
    if (!QueryFullProcessImageNameA(GetCurrentProcess(), 0, path, &size)) { return false; }
    if (std::strstr(path, expectedImage)) { return true; }
    return std::strstr(path, "YuanShen.exe") != nullptr;
}

int main(int argc, char** argv) {
    bool dry = false, checkIdentity = false, unknownConfig = false;
    std::int32_t configField = 0;
    const char* expectedImage = "YuanShen.exe";
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--dry") == 0) { dry = true; }
        else if (std::strcmp(argv[i], "--identity") == 0) { checkIdentity = true; }
        else if (std::strcmp(argv[i], "--config-unknown") == 0) { unknownConfig = true; }
        else if (std::strcmp(argv[i], "--image") == 0 && i + 1 < argc) { expectedImage = argv[++i]; }
        else if (std::strcmp(argv[i], "--config-field") == 0 && i + 1 < argc) {
            configField = (std::int32_t)std::strtol(argv[++i], nullptr, 10);
        }
    }
    const unsigned long long tick = (unsigned long long)GetTickCount64();
    unsigned identityChecked = 0, identityOk = 1;
    if (checkIdentity) {
        identityChecked = 1;
        identityOk = CurrentImageIsTarget(expectedImage) ? 1u : 0u;
        if (!identityOk) {
            std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"TARGET_IMAGE_MISMATCH\","
                        "\"image\":\"%s\",\"tick\":%llu}\n", expectedImage, tick);
            return 2;
        }
    }
    if (DS_DEADLINE_TICK != 0 && tick > (unsigned long long)DS_DEADLINE_TICK) {
        std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"DEADLINE_EXPIRED\",\"tick\":%llu,"
                    "\"deadline\":%llu}\n", tick, (unsigned long long)DS_DEADLINE_TICK);
        return 3;
    }
    ReadSource source{};
    if (dry) {
        sim::Init();
        sim::Add(8);                       // 预置一行（kind 8），after 计数应为 2
        source = ReadSource{nullptr, sim::Read};
    } else {
        // 真实通道：守卫通过才派发。**调用一旦开始 executed=true，exit!=0 也不降级。**
        if (GetCurrentProcessId() != (DWORD)HR_TARGET_PID) {
            std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"HOOK_NOT_IN_TARGET_PROCESS\","
                        "\"pid\":%lu,\"targetPid\":%lu,\"executed\":false,\"tick\":%llu}\n",
                        (unsigned long)GetCurrentProcessId(), (unsigned long)HR_TARGET_PID, tick);
            return 6;
        }
        HANDLE target = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                                    (DWORD)HR_TARGET_PID);
        if (!target) {
            std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"TARGET_PROCESS_NOT_OPEN\","
                        "\"pid\":%lu,\"executed\":false,\"tick\":%llu}\n",
                        (unsigned long)HR_TARGET_PID, tick);
            return 7;
        }
        char image[MAX_PATH * 2]{};
        DWORD size = sizeof(image);
        if (!QueryFullProcessImageNameA(target, 0, image, &size) ||
            !std::strstr(image, "YuanShen.exe")) {
            std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"TARGET_IMAGE_MISMATCH\","
                        "\"image\":\"%s\",\"executed\":false,\"tick\":%llu}\n", image, tick);
            CloseHandle(target);
            return 8;
        }
        ProcMem mem{target};
        source = ReadSource{&mem, ProcRead};
    }
    ConfigWritePlan plan{};
    plan.hasConfig = unknownConfig || configField > 0;
    plan.field = configField;
    plan.fieldSource = configField > 0 ? ConfigFieldSource::callerSupplied : ConfigFieldSource::none;
    plan.bytes = nullptr;
    plan.size = 0;
    plan.writerContext = nullptr;

    static ca::AttachmentWorkspace work;
    std::memset(&work, 0, sizeof(work));
    const Result attached = EnsureDropStuffAttached(source, &sim::Attach, sim::O, &work, &plan,
                                                    &sim::WriteBytes);
    static ca::CaptureWorkspace acceptWork;
    std::memset(&acceptWork, 0, sizeof(acceptWork));
    LedgerLine line{};
    const Code accepted = RawAccept(source, sim::O, attached.wrapper, &acceptWork, &line);
    const bool identityEqual = (attached.wrapper != 0) && (attached.wrapper == line.wrapper)
                               && accepted == Code::ok;
    const bool attachOk = attached.code == Code::ok || attached.code == Code::existing;
    const char* status = (attachOk && identityEqual) ? "ok" : "failed";
    std::printf("DSRAW1 {\"status\":\"%s\",\"kind\":%d,\"action\":%d,\"protocol\":%d,\"nonce\":%llu,"
                "\"attachCode\":\"%s\",\"acceptCode\":\"%s\",\"wrapperIdentity\":%d,"
                "\"readbackVerified\":%d,\"sourceBefore\":\"%s\",\"sourceAfter\":\"%s\","
                "\"configField\":%d,\"configFieldSource\":%d,\"configWritten\":%d,"
                "\"attachCalls\":%u,\"snapshotRowsBefore\":%u,\"snapshotRowsAfter\":%u,\"identityChecked\":%u,"
                "\"tick\":%llu}\n",
                status, (int)DS_KIND, (int)DS_ACTION_CODE, (int)DS_RECEIPT_VERSION,
                (unsigned long long)DS_NONCE, CodeName(attached.code), CodeName(accepted),
                identityEqual ? 1 : 0, line.independentReadback ? 1 : 0,
                line.sourceOfBaseline ? line.sourceOfBaseline : "",
                line.sourceOfAfter ? line.sourceOfAfter : "",
                (int)attached.configField, (int)plan.fieldSource, attached.configWritten ? 1 : 0,
                sim::g_calls, attached.before_count, attached.after_count, identityChecked, tick);
    return (attachOk && identityEqual) ? 0 : 5;
}
"""

_CPP_PROBE = r"""// 固定 probe（drop_stuff_attach.py 生成）：**只读**采集 owner 的组件行 + 指定 kind 的 config 头段。
// 用法: dropstuff_probe.exe <pid> <ownerHex> [configKind]
#include "dropstuff_kind37.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace ca = ge::component_attachment;
using namespace dropstuff;

struct ProcMem { HANDLE process; };
static bool ProcRead(void* ctx, std::uint64_t a, void* t, std::size_t s) noexcept {
    ProcMem* p = static_cast<ProcMem*>(ctx);
    SIZE_T done = 0;
    return p && p->process &&
           ReadProcessMemory(p->process, reinterpret_cast<LPCVOID>(a), t, s, &done) && done == s;
}

int main(int argc, char** argv) {
    if (argc < 3) { std::printf("usage: dropstuff_probe <pid> <ownerHex> [configKind]\n"); return 2; }
    const DWORD pid = (DWORD)std::strtoul(argv[1], nullptr, 10);
    const std::uint64_t owner = std::strtoull(argv[2], nullptr, 16);
    const std::int32_t kind = (argc > 3) ? (std::int32_t)std::strtol(argv[3], nullptr, 10) : DS_KIND;
    ProcMem mem{OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid)};
    if (!mem.process) {
        std::printf("DSRAW1 {\"status\":\"refused\",\"code\":\"OPEN_PROCESS_FAILED\",\"pid\":%lu}\n",
                    (unsigned long)pid);
        return 3;
    }
    ReadSource source{&mem, ProcRead};
    static ca::CaptureWorkspace work;
    std::memset(&work, 0, sizeof(work));
    ca::ComponentSnapshot snap{};
    ca::CaptureComponents(source, owner, &work, &snap);
    std::printf("DSRAW1 {\"status\":\"%s\",\"pid\":%lu,\"owner\":%llu,\"captureCode\":%u,"
                "\"rowCount\":%u,\"action\":%d,\"protocol\":%d,\"nonce\":%llu}\n",
                snap.code == ca::CaptureCode::complete ? "ok" : "failed", (unsigned long)pid,
                (unsigned long long)owner, (unsigned)snap.code, snap.count,
                (int)DS_ACTION_CODE, (int)DS_RECEIPT_VERSION, 0ull);
    for (std::uint32_t i = 0; i < snap.count; ++i) {
        const ca::ComponentRow& row = snap.rows[i];
        std::printf("DSRAW1 {\"w\":\"row\",\"index\":%u,\"kind\":%d,\"wrapper\":%llu,\"config\":%llu,"
                    "\"enabled\":%u}\n", i, (int)row.kind, (unsigned long long)row.wrapper,
                    (unsigned long long)row.config, (unsigned)row.enabled);
    }
    ConfigDump dump{};
    const Code dumped = DumpRowConfig(source, owner, kind, &work, &dump);
    std::printf("DSRAW1 {\"w\":\"config\",\"kind\":%d,\"code\":\"%s\",\"size\":%u,\"head\":\"",
                (int)kind, CodeName(dumped), dump.size);
    for (std::uint32_t i = 0; i < dump.size; ++i) { std::printf("%02x", dump.bytes[i]); }
    std::printf("\"}\n");
    CloseHandle(mem.process);
    return 0;
}
"""

_CPP_ACTION20 = r"""// hook/dropstuff_action20.cpp —— 本模块的 action 20 实现。
// 共享 game_scene_action.cpp 在 (320) 有故意门 `#error "Unsupported fixed action"`（其 action 表
// inspect:0/create:1/creature-create:1/save:2/create-batch:3，**明确不支持 20**）；本 TU 不剪共享
// #error、不改共享源，而是自带同名入口符号，供共享 hook_receipt.cpp 在 `#if HR_ACTION` 下调用。
// 所有字段与状态码均照共享头：GameSceneActionResult（game_scene_action.h:11-33）与
// GameContextSnapshot/GameEntitySnapshot（game_context_snapshot.h:95-128）；不编字段、不编数值。
#include "dropstuff_kind37.h"
#include "game_scene_action.h"
#include "game_context_snapshot.h"
#include <cstring>

namespace ca = ge::component_attachment;
using namespace dropstuff;

namespace {

// 进程内只读：共享头明写快照即 in-process read-only（game_context_snapshot.h:124），
// 故读源就是进程内 memcpy —— 无游戏方法、无堆分配、无文件 I/O。
bool InProcessRead(void* ctx, std::uint64_t address, void* target, std::size_t size) noexcept {
    (void)ctx;
    if (address == 0 || target == nullptr || size == 0) { return false; }
    std::memcpy(target, reinterpret_cast<const void*>(address), size);
    return true;
}

}  // namespace

// 链接说明：共享 game_scene_action.h:34 以 **C++ 链接**声明该入口（无 extern "C"），
// 故此处照头文件原样定义，不加 extern "C"（加了会 C2732 linkage 冲突）。
void ExecuteGameSceneAction(const GameContextSnapshot* before, GameSceneActionResult* out) {
    if (before == nullptr || out == nullptr) { return; }
    std::memset(out, 0, sizeof(*out));
    out->size = static_cast<std::uint32_t>(sizeof(GameSceneActionResult));
    out->version = 1;
    out->action = static_cast<std::uint32_t>(DS_ACTION_CODE);
    out->expectedLevelId = static_cast<std::uint32_t>(HR_EXPECTED_LEVEL);
    out->after = *before;
    out->status = 1;                       // 1 = invalid snapshot（默认拒绝）
    if (before->structSize != sizeof(GameContextSnapshot) || before->version != kSnapshotVersion) { return; }
    if (before->status != GS_OK || (before->flags & GS_ENTITIES_COMPLETE) == 0) { return; }
    out->levelId = before->reserved;       // 仅当 GS_LEVEL_OBSERVED 置位时该字段是关卡 id
    if ((before->flags & GS_LEVEL_OBSERVED) != 0 && out->levelId != out->expectedLevelId) {
        out->status = 5;                   // 5 = level mismatch
        return;
    }
    if (before->entityCaptured == 0) { return; }
    if (before->moduleBase == 0) { out->status = 4; return; }   // 4 = module/level manager unreadable

    ca::AttachmentWorkspace work{};
    std::memset(&work, 0, sizeof(work));
    ReadSource source{nullptr, InProcessRead};
    using AttachFn = void* (__cdecl*)(void*, std::int32_t);
    AttachFn attach = reinterpret_cast<AttachFn>(before->moduleBase + DS_ATTACH_RVA);
    // 宿主 = 快照第 0 个实体的 owner 字段（GameEntitySnapshot.owner，game_context_snapshot.h:96）；
    // 选取结果写进 result.owner，便于上层核对，不做隐式猜测。
    const std::uint64_t owner = before->entities[0].owner;
    const Result result = EnsureDropStuffAttached(source, attach, owner, &work, nullptr, nullptr);
    out->owner = owner;
    out->called = 1;
    out->callCode = static_cast<std::uint32_t>(result.code);
    if (result.code == Code::ok || result.code == Code::existing) {
        out->status = 0;                   // 0 = completed（call 的回执，不是持久化证据）
        out->entityId = static_cast<std::uint32_t>(owner);
    } else {
        out->status = 7;                   // 7 = native call rejected
    }
    CaptureGameContextSnapshot(&out->after);   // 真实 after 快照（进程内只读）
}

"""

_SCHEMA = {
    "schemaVersion": 1,
    "kind": "dropstuff-toolchain-schema-v1",
    "kindString": KIND_STRING,
    "action": {"code": ACTION_CODE, "name": "attach-dropstuff-kind37"},
    "receipt": {"protocol": RECEIPT_VERSION, "channel": "raw-log", "marker": "DSRAW1",
                "fields": ["status", "kind", "action", "protocol", "nonce", "attachCode", "acceptCode",
                           "wrapperIdentity", "readbackVerified", "sourceBefore", "sourceAfter",
                           "configField", "configFieldSource", "configWritten", "attachCalls",
                           "snapshotRowsBefore", "snapshotRowsAfter", "identityChecked", "tick"]},
    "guards": ["target-image", "nonce-echo", "deadline-tick", "hotfix-bytes",
               "wrapper-identity-equality", "independent-readback"],
    "cli": {"prepare": "--prepare [--out DIR] [--run-id ID]",
            "compileCheck": "--compile-check <RUN_DIR> [VCVARS64]"},
    "dispatch": {"gameDispatch": False, "note": "开发期关闭；由 root 在统一阶段对接 native-card route"},
}

ISOLATED_SOURCE_FILES: tuple[str, ...] = (
    "component_attachment.h", "component_attachment.cpp",
    "template_catalog_capture.h", "template_catalog.h",
)
ISOLATED_EXTRA_FILES: tuple[tuple[Path, str], ...] = (
    # 隔离副本**保留原树相对布局**：template_catalog_capture.h 里是
    # #include "../native/game_context_snapshot.h"，所以它在副本里必须仍在 isolated-source 的兄弟目录 native/。
    (SHARED_NATIVE_EXTRA / "game_context_snapshot.h", "native/game_context_snapshot.h"),
    # ② 真接共享 hook：入口/Wait/unhook 的协议头 + 实现（只读复制，产出**同名** hook_receipt.dll）
    (SHARED_NATIVE_EXTRA / "hook_receipt_protocol.h", "native/hook_receipt_protocol.h"),
    (SHARED_NATIVE_EXTRA / "hook_receipt.cpp", "native/hook_receipt.cpp"),
    # 同源 probe（17,767 B）：只 include 协议头 + 标准头，产出**同名** hook_receipt_probe.exe
    (SHARED_NATIVE_EXTRA / "hook_receipt_probe.cpp", "native/hook_receipt_probe.cpp"),
    # `hook_receipt_protocol.h:43` 的 `#if HR_ACTION` 会 include `game_scene_action.h`；
    # 该头只 include `game_context_snapshot.h`（已隔离）⇒ include 闭包到此闭合（实测 1,978 B）。
    (SHARED_NATIVE_EXTRA / "game_scene_action.h", "native/game_scene_action.h"),
    # 链接期需要这两个实现的**符号定义**（LNK2019 CaptureGameContextSnapshot / ExecuteGameSceneAction）
    (SHARED_NATIVE_EXTRA / "game_context_snapshot.cpp", "native/game_context_snapshot.cpp"),
    (SHARED_NATIVE_EXTRA / "game_scene_action.cpp", "native/game_scene_action.cpp"),
    # game_scene_action.cpp:4 需要 scene_calls.h（按 owner 口径：继续只读隔离并链，不剪 #if/不用空壳头）
    (SHARED_NATIVE_EXTRA / "scene_calls.h", "native/scene_calls.h"),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _anchor_literal(name: str) -> str:
    """由 native profile 的 anchors 字节表生成 C 字节表字面量。

    照 `build_readonly_profile.py:71-72` 的同族形式（`','.join(hex(b) …)`）；键缺失即返回 ``0``
    （卡片侧会记 refusal，**不编字节**）。
    """
    try:
        profiles = _load_native_profiles()
        row = (profiles.load_profile().get("anchors") or {})[name]
        data = bytes.fromhex(str(row["bytes"]))
    except Exception:
        return "0"
    return ",".join(hex(byte) for byte in data)


def emit_toolchain_files(*, nonce: int, deadline_tick: int, target_config: dict,
                         session: dict | None = None) -> dict[str, str]:
    """一次性候选目录里的**固定**源码/配置（键 = 相对路径）。

    ``session`` = 真实原生会话五元组；**未给**时按"未绑定"填 0/空串（候选目录仍可编译，
    但 ``run.json`` 记 ``sessionBound: false``）——不冒充已绑定会话。
    """
    session_bound = bool((session or {}).get("pid"))
    macros = (_TARGET_CONFIG_H
              .replace("@@ACTION@@", str(ACTION_CODE))
              .replace("@@PROTOCOL@@", str(RECEIPT_VERSION))
              .replace("@@KIND@@", str(_ACTIVE_KIND)).replace("@@KINDSTRING@@", kind_string_for(_ACTIVE_KIND))
              .replace("@@ATTACHRVA@@", ATTACH_ABI["rva"])
              .replace("@@NONCE@@", str(nonce))
              .replace("@@DEADLINE@@", str(deadline_tick))
              # 五个真实 session 宏（此前只替了 _TARGET_CONFIG_H 的前 6 个占位 ⇒ 生成物残留 @@PID@@
              # → `error C2018: unknown character '0x40'`，rev25 真构建抓到；未给 session 时按未绑定填 0）
              .replace("@@PID@@", str(int((session or {}).get("pid", 0))))
              .replace("@@TID@@", str(int((session or {}).get("tid", 0))))
              .replace("@@CREATION@@", str(int((session or {}).get("processCreation", 0))))
              .replace("@@THREADCREATION@@", str(int((session or {}).get("threadCreation", 0))))
              .replace("@@IMAGE@@", str((session or {}).get("image", "")).replace("\\", "\\\\"))
              # 见模板注释：MESSAGEID 未由 route 给出时按 0 写出，且卡片不声称可派发
              .replace("@@MESSAGEID@@", str(int((target_config or {}).get("messageId") or 0)))
              # 两个锚点由 native profile 的 anchors 字节表生成（只读；缺失即留空并在卡片记 refusal）
              .replace("@@LEVELANCHOR@@", _anchor_literal("LEVEL"))
              .replace("@@PLACEANCHOR@@", _anchor_literal("PLACE"))
              .replace("@@SAVEANCHOR@@", _anchor_literal("SAVE"))
              .replace("@@ENTITYIDS@@", str((target_config or {}).get("entityIds") or 0)))
    meta = {"schemaVersion": 2, "kindString": kind_string_for(_ACTIVE_KIND), "actionCode": ACTION_CODE,
            "receiptProtocol": RECEIPT_VERSION, "nonce": nonce, "deadlineTick": deadline_tick,
            "targetConfig": target_config, "kind": _ACTIVE_KIND,
            "kindRunLedger": {str(k): v for k, v in KIND_RUN_LEDGER.items()},
            "configCollection": dict(config_collection_plan(), kindString=kind_string_for(_ACTIVE_KIND)),
            "gameDispatch": False,
            # messageId 三处相等契约的第 1 处（另两处 = prepared.json / build-result.json）
            "messageId": int((target_config or {}).get("messageId") or 0),
            "messageIdSource": ("registered" if target_config.get("messageIdRegistration", {})
                                .get("ok") else "unregistered")}
    return {
        "include/dropstuff_target_config.h": macros,
        "include/dropstuff_kind37.h": _H_KIND37,
        "hook/dropstuff_kind37.cpp": _CPP_KIND37,
        # kind4 生产 TU（`AttachKind4Production` + 生产入口调用点）：落进候选的 native/ 并参与构建。
        "native/native_dropstuff.cpp": (REPO_ROOT / "tools/mondstadt/life/dropstuff/native/native_dropstuff.cpp").read_text(encoding="utf-8"),
        "hook/dropstuff_action20.cpp": _CPP_ACTION20,
        "hook/dropstuff_receipt_layout.cpp": _CPP_LAYOUT_PROBE,
        "wrapper/dropstuff_wrapper.cpp": _CPP_WRAPPER,
        "probe/dropstuff_probe.cpp": _CPP_PROBE,
        "schema/dropstuff-schema.json": json.dumps(_SCHEMA, ensure_ascii=False, indent=2) + "\n",
        "run.json": json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    }


#: **当前候选的 kind**（`--kind` 覆盖；默认 37 保持既有行为）。模板 `@@KIND@@` 与
#: `@@KINDSTRING@@` **两处替换站点**都用它 ⇒ 不会留下写死 37 的副本。
_ACTIVE_KIND: int = KIND_DROP_STUFF
#: kind4（Mover）的模块私有 kind 字符串（共享白名单 17/33/35 不含它）。
KIND_STRING_MOVER = "drop-mover"


def kind_string_for(kind: int) -> str:
    """kind → 模板里的 `DS_KIND_STRING`（kind4 走模块私有字符串）。"""
    return KIND_STRING_MOVER if int(kind) == KIND_DROP_MOVER else KIND_STRING


def prepare_candidate_dir(*, out_dir: Path | None = None, run_id: str | None = None,
                          nonce: int | None = None, ttl_ms: int = 600000,
                          session: dict | None = None, kind: int | None = None) -> dict:
    """**一次性候选目录**：每次 run 独立目录；已存在即具名拒绝（绝不复用上一次）。

    默认根 = ``.runtime/mondstadt-native/dropstuff/prepared/``（spec）；``out_dir`` 可覆盖。
    """
    global _ACTIVE_KIND
    # `--kind` 的落点：显式传入才覆盖；**未传时保留 `_main` 已解析的值**（否则会把 4 重置回 37）。
    if kind is not None:
        _ACTIVE_KIND = require_executable_kind(int(kind))
    run = run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    root = Path(out_dir) if out_dir is not None else (REPO_ROOT / PREPARED_ROOT)
    candidate = root / run
    if candidate.exists():
        raise AttachSpecError("CANDIDATE_DIR_EXISTS_REFUSING_REUSE",
                              f"{candidate} 已存在：一次性候选目录不得复用")
    candidate.mkdir(parents=True)
    for sub in ("isolated-source", "native", "include", "hook", "wrapper", "probe", "schema", "build"):
        (candidate / sub).mkdir(exist_ok=True)

    copied: dict[str, str] = {}
    source_hashes: dict[str, str] = {}
    for name in ISOLATED_SOURCE_FILES:
        origin = SHARED_NATIVE / name
        if not origin.is_file():
            raise AttachSpecError("ISOLATED_SOURCE_MISSING", f"缺少 {origin}")
        shutil.copyfile(origin, candidate / "isolated-source" / name)
        source_hashes[name] = _sha256_file(origin)
        copied[name] = str(origin)
    for origin, name in ISOLATED_EXTRA_FILES:
        if not origin.is_file():
            raise AttachSpecError("ISOLATED_SOURCE_MISSING", f"缺少 {origin}")
        target = candidate / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        source_hashes[name] = _sha256_file(origin)
        copied[name] = str(origin)

    target_config = build_target_config()
    # HR_MESSAGE_ID：**真实注册**（transport 不注册不造值）；注册失败 ⇒ 具名阻断 + 三处不写伪值
    registration = register_message_id()
    target_config["messageId"] = registration.get("messageId") or 0
    target_config["messageIdRegistration"] = {k: v for k, v in registration.items() if k != "name"}
    target_config["messageIdName"] = registration.get("name")
    chosen_nonce = (nonce if nonce is not None else int.from_bytes(os.urandom(8), "big")) | 1
    # deadline = 生成时刻的 uptime + ttl；wrapper 侧与 GetTickCount64() 比。0 = 不检查（dry/离线）。
    now = _uptime_ms()
    deadline = (now + int(ttl_ms)) if now else 0
    files = emit_toolchain_files(nonce=chosen_nonce, deadline_tick=deadline,
                                 target_config=target_config, session=session)
    # @@RUN@@ → 本候选目录的**绝对**路径，且反斜杠加倍（C++ 宽字面量里必须是 `\\`）
    run_literal = str(Path(candidate).resolve()).replace("\\", "\\\\")
    files = {name: text.replace("@@RUN@@", run_literal)
             for name, text in files.items()}
    session_bound = bool((session or {}).get("pid") and (session or {}).get("tid"))
    (candidate / "run.json").parent.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for rel, text in files.items():
        path = candidate / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written[rel] = len(text.encode("utf-8"))

    build_cmd = _build_script(candidate, session_bound=session_bound)
    (candidate / "build" / "build.cmd").write_bytes(build_cmd.encode("ascii"))
    written["build/build.cmd"] = len(build_cmd.encode("ascii"))

    return {"ok": True, "runId": run, "candidateDir": str(candidate), "oneShot": True,
            "reuseRefused": "CANDIDATE_DIR_EXISTS_REFUSING_REUSE",
            "nonce": chosen_nonce, "deadlineTick": deadline,
            "isolatedSource": {"files": copied, "sha256": source_hashes,
                               "mode": "isolated-source-copy（原文件只读，不改）"},
            "written": written, "targetConfig": target_config, "gameDispatch": False}


def register_message_id() -> dict:
    """真实注册 Windows 消息号（照 prepare_item.py:149-166 的做法）。

    命名 = ``'Miliastra.MondstadtDropStuff.' + token_hex(16)``；校验 ``0xC000 <= id <= 0xFFFF``；
    越界或返回 0 ⇒ 具名阻断（**不编数字**）。这是用户态消息注册：不开窗口、不触达游戏、不写存档。
    """
    name = "Miliastra.MondstadtDropStuff." + os.urandom(16).hex()   # = token_hex(16)
    try:
        import ctypes
        value = int(ctypes.windll.user32.RegisterWindowMessageW(ctypes.c_wchar_p(name)))
    except Exception as error:  # pragma: no cover
        return {"ok": False, "code": "MESSAGE_ID_REGISTER_FAILED",
                "detail": f"{type(error).__name__}: {error}", "name": name}
    if not 0xC000 <= value <= 0xFFFF:
        return {"ok": False, "code": "MESSAGE_ID_OUT_OF_RANGE",
                "detail": f"RegisterWindowMessageW 返回 {value!r}，不在 0xC000..0xFFFF", "name": name}
    return {"ok": True, "messageId": value, "name": name}


def _build_script(candidate: Path, *, session_bound: bool = False) -> str:
    """固定构建脚本（**纯 ASCII + CRLF**：cmd.exe 对 UTF-8/中文/LF-only 的解析不可靠）。"""
    lines = [
        "@echo off",
        "REM Fixed build for this one-shot candidate dir (generated by --prepare).",
        "REM Usage: build.cmd <RUN_DIR> [VCVARS64]   (read-only use of isolated-source)",
        "setlocal",
        'set "RUN=%~1"',
        f'if not defined RUN set "RUN={candidate}"',
        'set "VCVARS=%~2"',
        'if not defined VCVARS set "VCVARS=C:\\Program Files\\Microsoft Visual Studio\\2022'
        '\\Community\\VC\\Auxiliary\\Build\\vcvars64.bat"',
        'call "%VCVARS%" >nul 2>&1',
        "if errorlevel 1 (echo VCVARS_MISSING & exit /b 2)",
        'set "SHARED=%RUN%\\isolated-source"',
        f'set "DS_SESSION_BOUND={"1" if session_bound else "0"}"',
        'set "INC1=%RUN%\\include"',
        'cd /d "%RUN%\\build"',
        "if errorlevel 1 exit /b 3",
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '"%RUN%\\hook\\dropstuff_kind37.cpp"',
        "if errorlevel 1 exit /b 4",
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '"%SHARED%\\component_attachment.cpp"',
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '"%RUN%\\native\\native_dropstuff.cpp"',
        "if errorlevel 1 exit /b 5",
        'cl /nologo /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '/Fe:"%RUN%\\build\\dropstuff_layout.exe" "%RUN%\\hook\\dropstuff_receipt_layout.cpp"',
        "if errorlevel 1 exit /b 6",
        'cl /nologo /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '/Fe:"%RUN%\\build\\dropstuff_wrapper.exe" "%RUN%\\wrapper\\dropstuff_wrapper.cpp" '
        "dropstuff_kind37.obj component_attachment.obj",
        "if errorlevel 1 exit /b 7",
        'cl /nologo /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%SHARED%" '
        '/Fe:"%RUN%\\build\\dropstuff_probe.exe" "%RUN%\\probe\\dropstuff_probe.cpp" '
        "dropstuff_kind37.obj component_attachment.obj",
        "if errorlevel 1 exit /b 8",
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%RUN%\\native" '
        '/FI"%INC1%\\dropstuff_target_config.h" "%RUN%\\native\\hook_receipt.cpp" '
        '/Fo"hook_receipt.obj"',
        "if errorlevel 1 exit /b 9",
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%RUN%\\native" '
        '/FI"%INC1%\\dropstuff_target_config.h" "%RUN%\\native\\game_context_snapshot.cpp" '
        '/Fo"game_context_snapshot.obj"',
        "if errorlevel 1 exit /b 11",
        'cl /nologo /c /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%RUN%\\native" /I"%SHARED%" '
        '/FI"%INC1%\\dropstuff_target_config.h" "%RUN%\\hook\\dropstuff_action20.cpp" '
        '/Fo"dropstuff_action20.obj"',
        "if errorlevel 1 exit /b 12",
        'link /nologo /DLL /OUT:"%RUN%\\build\\hook_receipt.dll" hook_receipt.obj '
        'game_context_snapshot.obj dropstuff_action20.obj dropstuff_kind37.obj '
        'component_attachment.obj User32.lib',
        "if errorlevel 1 exit /b 10",
        "if not \"%DS_SESSION_BOUND%\"==\"0\" goto do_probe",
        "echo HOOK_PROBE_SKIPPED_SESSION_UNBOUND (HR_TARGET_PID/TID fixture 0; the shared probe "
        "asserts a real session -- see run.json sessionBound)",
        "goto after_probe",
        ":do_probe",
        'cl /nologo /utf-8 /std:c++17 /EHsc /W4 /WX /I"%INC1%" /I"%RUN%\\native" /I"%SHARED%" '
        '/FI"%INC1%\\dropstuff_target_config.h" "%RUN%\\native\\hook_receipt_probe.cpp" '
        '/Fo"%RUN%\\build\\hook_receipt_probe.obj" /Fe:"%RUN%\\build\\hook_receipt_probe.exe" '
        '/link User32.lib Advapi32.lib',
        "if errorlevel 1 exit /b 13",
        ":after_probe",
        "echo CHAIN_BUILD_OK %RUN%\\build",
        "endlocal",
    ]
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# 5. raw 日志：**独立 decode / accept**（偏移取自编译产物，不硬编码）
# ---------------------------------------------------------------------------

RAW_MARKER = "DSRAW1"

REQUIRED_LAYOUT_KEYS: tuple[str, ...] = (
    "action", "protocol", "kind", "kindString",
    "sizeof_Result", "offsetof_Result_code", "offsetof_Result_wrapper",
    "offsetof_Result_configField", "offsetof_Result_configWritten",
    "sizeof_ConfigWritePlan", "offsetof_ConfigWritePlan_field",
    "offsetof_ConfigWritePlan_fieldSource", "sizeof_ConfigDump", "configDumpBytes",
)


def decode_raw_receipt(line: str) -> dict:
    """把一行 raw 日志解码成 dict（**与写侧独立**；只认 ``DSRAW1`` + JSON 体）。"""
    text = line.strip()
    if not text.startswith(RAW_MARKER):
        raise AttachSpecError("RAW_MARKER_MISSING", f"不是 {RAW_MARKER} 行：{text[:60]!r}")
    body = text[len(RAW_MARKER):].strip()
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise AttachSpecError("RAW_JSON_INVALID", f"{error}: {body[:120]!r}") from None
    if not isinstance(decoded, dict):
        raise AttachSpecError("RAW_SHAPE_INVALID", "raw 行不是 JSON 对象")
    return decoded


def accept_raw_log(log_text: str, run_meta: dict, *, expected_kind: int = KIND_DROP_STUFF,
                   accept_config_refusal: bool = False) -> dict:
    """独立接受路径：逐行解码 → 校验 nonce/protocol/action/kind/身份/独立读回/计数增量。

    纪律：**同源自比不算同步证据**（两个 source 字符串必须不同）；不信任任何单边 sha。
    ``accept_config_refusal=True`` 时把 ``config_field_unknown`` 视作**正确的拒绝**（用于验证配置闸）。
    """
    lines = [line for line in log_text.splitlines() if line.strip().startswith(RAW_MARKER)]
    if not lines:
        raise AttachSpecError("RAW_LOG_EMPTY", "日志里没有 DSRAW1 行")
    receipts = [decode_raw_receipt(line) for line in lines]
    finals = [r for r in receipts if r.get("status") in ("ok", "failed", "refused")]
    if not finals:
        raise AttachSpecError("RAW_LOG_NO_FINAL", "没有最终收据行")
    final = finals[-1]
    if final.get("status") == "refused":
        return {"ok": False, "accepted": False, "code": final.get("code"), "receipt": final}
    nonce = int(run_meta.get("nonce", 0))
    if int(final.get("nonce", -1)) != nonce:
        raise AttachSpecError("RAW_NONCE_MISMATCH", f"nonce={final.get('nonce')!r} != {nonce}")
    if int(final.get("protocol", -1)) != RECEIPT_VERSION:
        raise AttachSpecError("RAW_PROTOCOL_MISMATCH", f"protocol={final.get('protocol')!r}")
    if int(final.get("action", -1)) != ACTION_CODE:
        raise AttachSpecError("RAW_ACTION_MISMATCH", f"action={final.get('action')!r}")
    if int(final.get("kind", -1)) != expected_kind:
        raise AttachSpecError("RAW_KIND_MISMATCH", f"kind={final.get('kind')!r}")
    if accept_config_refusal and final.get("attachCode") == "config_field_unknown":
        return {"ok": True, "accepted": True, "code": "RAW_CONFIG_GATE_CONFIRMED",
                "receipt": final, "rowLines": [r for r in receipts if r.get("w") == "row"],
                "configLines": [r for r in receipts if r.get("w") == "config"]}
    if not int(final.get("wrapperIdentity", 0)):
        raise AttachSpecError("RAW_WRAPPER_IDENTITY_NOT_PROVEN",
                              "wrapperIdentity=0：returned_wrapper == added.wrapper 未被证明")
    if not int(final.get("readbackVerified", 0)):
        raise AttachSpecError("RAW_READBACK_NOT_INDEPENDENT", "readbackVerified=0")
    if int(final.get("snapshotRowsAfter", -1)) != int(final.get("snapshotRowsBefore", -2)) + 1:
        raise AttachSpecError("RAW_DELTA_NOT_ONE_ROW",
                              f"before={final.get('snapshotRowsBefore')} "
                              f"after={final.get('snapshotRowsAfter')}")
    verify_attach_receipt({"beforeSource": final.get("sourceBefore"),
                           "afterSource": final.get("sourceAfter"),
                           "diff": {"addedRows": [{"kind": final.get("kind")}], "changedRows": []},
                           "expectedKind": expected_kind})
    return {"ok": True, "accepted": True, "code": "RAW_ACCEPTED", "receipt": final,
            "rowLines": [r for r in receipts if r.get("w") == "row"],
            "configLines": [r for r in receipts if r.get("w") == "config"]}


# ---------------------------------------------------------------------------
# 6. 真实配置采集（requirement 4）：采集路径 + 具名未知字段
# ---------------------------------------------------------------------------


def config_collection_plan() -> dict:
    """**真实配置采集**清单：不是只挂空组件。"""
    sample_path = PREFAB_DIR / DROPGATHER_SAMPLE["prefabFile"]
    return {
        "kindString": KIND_STRING, "approach": "read-only-collect-then-replay",
        "collector": "probe/dropstuff_probe.cpp（CaptureComponents + DumpRowConfig，只读）",
        "collectorModes": ["rows", "config-head（64 B hex）"],
        "knownSamples": [dict(DROPGATHER_SAMPLE, sharedSource=str(sample_path),
                              sharedSourcePresent=sample_path.is_file())],
        "targetKind": KIND_DROP_STUFF,
        "targetKindConfigField": None,
        "targetKindConfigFieldStatus": "unknown（0/2729 官方预制；两套普查都缺 37 且命名空间不同）",
        "fieldSources": [
            {"key": "measured-census", "usable": False,
             "why": f"普查里没有 37；已测 {sorted(MEASURED_PREFAB_ROW_CONFIG_FIELDS)}"},
            {"key": "collected-from-template", "usable": False,
             "why": "需要有带 kind 37 的官方模板做同 kind 采样；2729 份 0 命中 ⇒ 当前不可用"},
            {"key": "caller-supplied", "usable": True,
             "why": "人工在编辑器里配一次 DropStuff 内容组件后按实测字段号+出处传入（当前唯一可用）"},
        ],
        "writeSideGate": {"code": "config_field_unknown",
                          "behaviour": "有 config 但无具名字段来源时**拒绝**写入，不静默挂空组件"},
        "dispatch": {"gameDispatch": False},
    }


# ---------------------------------------------------------------------------
# 7. compile-check：真编译 + layout probe + dry 通道 + 独立解码
# ---------------------------------------------------------------------------


# ==== 执行链：图串联 → 可见掉落运动 → 拾取判定 → 归属防重复 =====================
# 这一段是**代码**（可读可核），运行期执行才归统一实机；不拿“归实机”代替实现。
PICKUP_TOLERANCE = 0.75          # 拾取判定半径（与数据集一致）
OWNERSHIP_FIELD = "ownerRef"     # 归属字段：同一 owner 对同一果实只允许入包一次


def movement_component_plan(*, tree_ref: str, fruit_ref: str, ground_y: float,
                            rise: float = 1.2) -> dict:
    """**运动元件接线（kind4 Mover）**：把运动组件挂到果实实体，并给出可见落果的两段位移。

    **坐标系统一**：两段 `from/to` 全用**世界绝对 Y**（此前 rising 用相对 `rise`、falling 用绝对
    `ground_y`，混用两种坐标系 —— 已修）。`rise` 只作为**相对抬升量**参与换算。
    """
    base = float(ground_y)
    top = base + float(rise)
    return {
        "moverKind": KIND_DROP_MOVER,
        "attachAbi": ATTACH_ABI["signature"],
        "attachRva": ATTACH_ABI["rva"],
        "sharedWhitelistUntouched": [17, 33, 35],
        "target": fruit_ref, "tree": tree_ref,
        "coordinateSystem": "world-absolute-y",
        "phases": [
            {"phase": "rising", "from": base, "to": top, "visible": True},
            {"phase": "falling", "from": top, "to": base, "visible": True},
        ],
        "landingGroundY": base,
    }


def graph_chain_wiring(*, tree_graph: str, fruit_graph: str) -> dict:
    """**图串联**：树图 → 命中 → 果实图（升→落→落地）→ 拾取，作为一条链的数据面。"""
    return {"chain": [tree_graph, "rising_named", "rise_gate", "falling_named",
                      "landed_gate", fruit_graph, "pickup"],
            "entry": tree_graph, "terminal": "pickup",
            "flowsAsOneChain": True}


def pickup_judgement(*, fruit_visible: bool, landed: bool, distance: float,
                     tolerance: float = PICKUP_TOLERANCE) -> dict:
    """**拾取判定**：必须可见 + 已落地 + 距离在容差内；否则具名拒绝。"""
    if not fruit_visible:
        return {"ok": False, "code": "PICKUP_NOT_VISIBLE"}
    if not landed:
        return {"ok": False, "code": "PICKUP_NOT_LANDED"}
    if float(distance) > float(tolerance):
        return {"ok": False, "code": "PICKUP_OUT_OF_RANGE",
                "distance": float(distance), "tolerance": float(tolerance)}
    return {"ok": True, "code": "PICKUP_ALLOWED", "distance": float(distance)}


def ownership_dedup(*, owner_ref: str, fruit_ref: str, seen: list | None = None) -> dict:
    """**归属防重复**：同一 (ownerRef, fruitRef) 只允许入包一次；重复即具名拒绝。"""
    granted = {(str(row.get("ownerRef")), str(row.get("fruitRef"))) for row in (seen or [])}
    key = (str(owner_ref), str(fruit_ref))
    if key in granted:
        return {"ok": False, "code": "OWNERSHIP_ALREADY_GRANTED", "key": list(key)}
    return {"ok": True, "code": "OWNERSHIP_GRANTED", "key": list(key),
            "field": OWNERSHIP_FIELD}


def execution_chain(*, trees: list | None = None) -> dict:
    """把四段串成**一条链**：每个果实 = 运动元件 + 图链 + 拾取判定 + 归属防重复。"""
    rows = list(trees or [])
    chain = []
    for row in rows:
        chain.append({
            "fruitRef": row.get("fruitRef"), "treeRef": row.get("treeRef"),
            "movement": movement_component_plan(tree_ref=str(row.get("treeRef")),
                                                fruit_ref=str(row.get("fruitRef")),
                                                ground_y=float(row.get("groundY") or 0.0)),
            "graphs": graph_chain_wiring(tree_graph=str(row.get("treeGraph")),
                                         fruit_graph=str(row.get("fruitGraph"))),
            "pickup": pickup_judgement(fruit_visible=True, landed=True, distance=0.0),
            "dedup": ownership_dedup(owner_ref="synthetic-offline",
                                     fruit_ref=str(row.get("fruitRef"))),
        })
    return {"ok": bool(chain), "chainCount": len(chain), "chains": chain,
            "note": "代码齐备；运行期执行归统一实机（本函数不接触游戏）"}


#: **共享契约模块**（`tools/editor-bridge/native-card/dispatch.py`，逐字事实由 owner 定位）：
#:   :145 `component_prepared(tool, source, built, *, fresh=False)` · :199 `component_acceptance(tool, source, prepared)`
#:   :42 `ROUTES['mondstadt-dropstuff']`（root/kind `mondstadt-dropstuff-build-v1`/wrapper/scope/action 20/protocol 25）
SHARED_CONTRACT_MODULE = "tools/editor-bridge/native-card/dispatch.py"
SHARED_CONTRACT_TOOL = "mondstadt-dropstuff"


#: 共享契约 `component_prepared` 要求的 `prepared.json` 必填面（逐条来自 `dispatch.py:145-177`）。
PREPARED_DOC_REQUIRED = ("kind", "launchable", "compileOnly", "reviewed", "allowWrites",
                         "actionCode", "receiptVersion", "levelId", "scope", "wrapperName",
                         "session", "nonce", "deadline", "messageId", "expiresUtc",
                         "baselineRun", "baselineSha256", "normalizedSpecSha256", "sourceHashes")
#: 该文档里**必须来自真实登记/真实采集**的输入（缺一项就写不出合法文档，绝不编造）。
PREPARED_DOC_LIVE_INPUTS = ("messageId", "baselineRun", "baselineSha256",
                            "normalizedSpecSha256", "sourceHashes")


def emit_shared_prepared_doc(*, source: Path | str, live_inputs: dict | None = None,
                             write: bool = False) -> dict:
    """产出共享契约的 `source/prepared.json`（**只写真实输入**，缺项即具名拒绝）。

    * `live_inputs` 必须来自**真实登记/真实采集**：`messageId`（路由登记的 0xc000..0xffff）、
      `baselineRun`（`.runtime/...` 下的真实基线运行目录）、`baselineSha256`、
      `normalizedSpecSha256`、`sourceHashes`（含 `<componentFolder>/native_acceptance.py` 的摘要）。
    * 缺任何一项 ⇒ **`PREPARED_DOC_LIVE_INPUTS_MISSING`** 并列出具名缺项；**不编造** messageId/基线。
    * 五条布尔闸与三个绑定值来自本通道的真实常量（`ACTION_CODE=20`/`RECEIPT_VERSION=25`/
      `ATTACH_ABI`/`KIND_STRING`/`TRANSPORT_SCOPE`）。
    """
    source_path = Path(source)
    supplied = dict(live_inputs or {})
    missing = [key for key in PREPARED_DOC_LIVE_INPUTS if not supplied.get(key)]
    if missing:
        return {"ok": False, "code": "PREPARED_DOC_LIVE_INPUTS_MISSING",
                "missing": missing,
                "why": ("这些字段必须来自真实登记/真实采集（messageId 登记、基线运行目录、"
                        "spec/基线摘要、acceptor 源码摘要）；**离线阶段不得编造**"),
                "requiredBy": "tools/editor-bridge/native-card/dispatch.py:145-177"}
    message_id = int(supplied["messageId"])
    if not (0xc000 <= message_id <= 0xFFFF):
        return {"ok": False, "code": "COMPONENT_REGISTERED_MESSAGE_RANGE",
                "messageId": message_id, "range": [0xC000, 0xFFFF]}
    doc = {
        "kind": KIND_STRING.replace("-build-", "-prepared-"),
        "launchable": True, "compileOnly": False, "reviewed": True, "allowWrites": True,
        "actionCode": ACTION_CODE, "receiptVersion": RECEIPT_VERSION,
        "levelId": int(supplied.get("levelId") or 1073741843),
        "scope": TRANSPORT_SCOPE, "wrapperName": supplied.get("wrapperName") or "invoke-mondstadt-dropstuff.ps1",
        "session": supplied.get("session"), "nonce": int(supplied.get("nonce") or 0),
        "deadline": int(supplied.get("deadline") or 0), "messageId": message_id,
        "expiresUtc": supplied.get("expiresUtc"),
        "baselineRun": str(supplied["baselineRun"]), "baselineSha256": supplied["baselineSha256"],
        "normalizedSpecSha256": supplied["normalizedSpecSha256"],
        "sourceHashes": dict(supplied["sourceHashes"]),
    }
    missing_doc = [key for key in PREPARED_DOC_REQUIRED if doc.get(key) in (None, "", {})]
    if missing_doc:
        return {"ok": False, "code": "PREPARED_DOC_FIELDS_MISSING", "missing": missing_doc}
    path = source_path / "prepared.json"
    if write:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "code": "PREPARED_DOC_READY", "path": str(path), "written": bool(write),
            "doc": doc}


def production_call_site(tu_path: Path | str | None = None) -> dict:
    """**第 3 件证据之三：调用点**（TU 里哪一行调 `AttachKind4Production`、位于哪个函数）。

    只读解析源码，不改 TU。返回 `{ok, tu, callSites:[{line, function, code}], functions}`。
    """
    path = Path(tu_path) if tu_path else (REPO_ROOT / "tools/mondstadt/life/dropstuff/native/native_dropstuff.cpp")
    if not path.is_file():
        return {"ok": False, "code": "TU_MISSING", "tu": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    functions: list[tuple[int, str]] = []
    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if "(" in stripped and ")" in stripped and stripped.endswith(("{", ") {")) or \
                (stripped.endswith(")") and index < len(lines) and lines[index].strip() == "{"):
            name = stripped.split("(")[0].split()[-1] if "(" in stripped else ""
            if name and not name.startswith(("if", "for", "while", "switch", "return")):
                functions.append((index, name))
    call_sites: list[dict] = []
    for index, line in enumerate(lines, 1):
        if "AttachKind4Production" in line and "(" in line and "&AttachKind4Production" not in line:
            enclosing = [name for start, name in functions if start <= index]
            call_sites.append({"line": index, "function": enclosing[-1] if enclosing else "<file-scope>",
                               "code": line.strip()[:120]})
    return {"ok": bool(call_sites), "tu": str(path), "tuBytes": path.stat().st_size,
            "callSites": call_sites,
            "functionCount": len(functions),
            "attached": bool(call_sites)}


# ---------------------------------------------------------------------------
# 第 3 件证据之四：**G5 真实调用链**（磁盘 raw 回执核对 + 补充源码接线）
# ---------------------------------------------------------------------------
#: raw 回执（生产序列化产物）的**字段名清单**。与 `native_dropstuff.cpp:SerializeBeforeAfter` 逐字对齐：
#: before/after **旧组件保全** + **新 kind4 wrapper / owner / config**。
RAW_RECEIPT_FIELDS: tuple[str, ...] = (
    "phase", "kind", "code", "evidenceGateGap", "owner",
    "oldOwnerBefore", "oldOwnerAfter", "countBefore", "countAfter",
    "captureCodeBefore", "captureCodeAfter", "beforeRows", "afterRows",
    "oldComponentsPreserved", "newKind4",
)
#: 组件行字段（beforeRows[] / afterRows[] 每行）。
RAW_RECEIPT_ROW_FIELDS: tuple[str, ...] = (
    "wrapper", "wrapperClass", "config", "configClass", "kind", "enabled",
)
#: 旧组件保全行字段（oldComponentsPreserved[]）。
RAW_RECEIPT_OLD_FIELDS: tuple[str, ...] = ("wrapper", "kind", "present")
#: 新 kind4 身份字段（newKind4）。
RAW_RECEIPT_NEW_KIND_FIELDS: tuple[str, ...] = (
    "wrapper", "owner", "config", "configClass", "present", "wrapperInAfter",
)
#: 默认落盘位置（fixture 不给 argv 时也写这两处；相对工程根）。
RAW_RECEIPT_ARTIFACT = ".life-dropstuff-out/nds_before_after.json"
RAW_VERDICT_ARTIFACT = ".life-dropstuff-out/nds_chain_verdict.json"
#: fixture 段**禁止**出现的生产符号**调用**：出现即「验证走错链」（fixture 自调序列化/生产本体）。
FIXTURE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "SerializeBeforeAfter(", "AttachKind4Production(", "EnsureKind4AttachedProduction(",
)
#: 生产段的唯一序列化调用（负控判据的锚点）。
PRODUCTION_SERIALIZE_CALL = "SerializeBeforeAfter(before, after, out, sink);"


def _strip_cpp_comments(text: str) -> str:
    """去掉 C/C++ 注释但**保留行数**（用空格替换，换行保留）⇒ 行号仍可对源码。"""
    out: list[str] = []
    index = 0
    size = len(text)
    in_line = False
    in_block = False
    while index < size:
        char = text[index]
        nxt = text[index + 1] if index + 1 < size else ""
        if in_line:
            if char == "\n":
                in_line = False
                out.append(char)
            else:
                out.append(" ")
            index += 1
            continue
        if in_block:
            if char == "*" and nxt == "/":
                out.append("  ")
                index += 2
                in_block = False
            else:
                out.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if char == "/" and nxt == "/":
            in_line = True
            out.append("  ")
            index += 2
            continue
        if char == "/" and nxt == "*":
            in_block = True
            out.append("  ")
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _brace_span(lines: list[str], start: int) -> tuple[int, int]:
    """从 `start` 行开始按花括号配对求函数体行区间（0 基、含首尾）；失败返回 `(start, len-1)`。"""
    if start < 0 or start >= len(lines):
        return (start, start)
    depth = 0
    opened = False
    for index in range(start, len(lines)):
        for char in lines[index]:
            if char == "{":
                depth += 1
                opened = True
            elif char == "}":
                depth -= 1
                if opened and depth == 0:
                    return (start, index)
    return (start, len(lines) - 1)


def _tu_fixture_block(text: str) -> tuple[int, int, str]:
    """`#ifdef NDS_FIXTURE` … `#endif  // NDS_FIXTURE` 的字符区间与子串（找不到即空）。"""
    start = text.find("#ifdef NDS_FIXTURE")
    if start < 0:
        return (0, 0, "")
    end = text.find("#endif  // NDS_FIXTURE", start)
    if end < 0:
        end = len(text)
    else:
        end += len("#endif  // NDS_FIXTURE")
    return (start, end, text[start:end])


def production_chain_sites(tu_path: Path | str | None = None) -> dict:
    """**补充**的源码接线核查（`RAW_SERIALIZATION_CALL_MISSING` 在这里；**它不能替代调用链**）。

    真实判据是 `/DNDS_FIXTURE` 可执行文件产出的**回执字节**（见 `raw_receipt_chain_check`）：
    回执必须经 ``NdsKind4EnsureAttachedEntry → EnsureKind4AttachedProduction（noinline）
    → AttachKind4Production → CaptureComponents(before/after) → attach(owner,4)
    → SerializeBeforeAfter`` 产出；`fixture` 段若自己直调序列化器/生产本体，就是「验证走错链」的
    反模式（上一轮删掉生产调用仍 exit=0/942 B 的根因），本检查器把它判成 `FIXTURE_BYPASSES_PRODUCTION_CHAIN`。
    """
    path = Path(tu_path) if tu_path else (REPO_ROOT / "tools/mondstadt/life/dropstuff/native/native_dropstuff.cpp")
    if not path.is_file():
        raise AttachSpecError("TU_MISSING", str(path))
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    stripped = _strip_cpp_comments(text)
    lines = stripped.splitlines()

    def find(predicate) -> int:
        return next((index for index, line in enumerate(lines) if predicate(line)), -1)

    body_start = find(lambda line: "ProdReceipt AttachKind4Production(" in line)
    entry_start = find(lambda line: "EnsureKind4AttachedProduction(" in line and "noinline" in line)
    export_start = find(lambda line: "NdsKind4EnsureAttachedEntry()" in line and "dllexport" in line)
    body_span = _brace_span(lines, body_start) if body_start >= 0 else (-1, -1)
    entry_span = _brace_span(lines, entry_start) if entry_start >= 0 else (-1, -1)

    def lines_in(span: tuple[int, int], needle: str) -> list[int]:
        if span[0] < 0:
            return []
        return [index + 1 for index in range(span[0], min(span[1] + 1, len(lines)))
                if needle in lines[index]]

    serialize_lines = lines_in(body_span, "SerializeBeforeAfter(")
    attach_lines = lines_in(body_span, "attach(reinterpret_cast<void*>(owner), kRuntimeKindMover)")
    capture_before = lines_in(body_span, "ca::CaptureComponents(rs, owner, ws, &before)")
    capture_after = lines_in(body_span, "ca::CaptureComponents(rs, owner, ws, &after)")
    entry_call_lines = lines_in(entry_span, "AttachKind4Production(")

    fixture_start, fixture_end, fixture_text = _tu_fixture_block(text)
    fixture_stripped = _strip_cpp_comments(fixture_text)
    fixture_entry_calls = fixture_stripped.count("NdsKind4EnsureAttachedEntry(")
    fixture_forbidden = {needle: fixture_stripped.count(needle) for needle in FIXTURE_FORBIDDEN_CALLS}
    fixture_dirty = {needle: count for needle, count in fixture_forbidden.items() if count}
    fixture_block_lines = (
        (text[:fixture_start].count("\n") + 1, text[:fixture_end].count("\n") + 1)
        if fixture_text else (0, 0))

    if serialize_lines:
        code = "PRODUCTION_CHAIN_WIRED"
    elif fixture_dirty:
        code = "FIXTURE_BYPASSES_PRODUCTION_CHAIN"
    else:
        code = "RAW_SERIALIZATION_CALL_MISSING"
    if serialize_lines and fixture_dirty:
        code = "FIXTURE_BYPASSES_PRODUCTION_CHAIN"
    ok = bool(
        body_start >= 0 and len(serialize_lines) == 1 and attach_lines
        and len(capture_before) == 1 and len(capture_after) == 1
        and entry_start >= 0 and entry_call_lines and export_start >= 0
        and fixture_entry_calls >= 1 and not fixture_dirty)
    if not ok and code == "PRODUCTION_CHAIN_WIRED":
        code = "PRODUCTION_CHAIN_INCOMPLETE"
    return {
        "ok": ok,
        "code": code,
        "supplementaryOnly": True,
        "why": ("源码字符串检查只是补充：接通判据 = fixture 经生产入口产出的回执字节 + 破坏生产调用后回执为空/缺失；"
                "不得以「grep 到调用」当接通"),
        "tuPath": str(path),
        "tuBytes": len(raw),
        "tuSha256": hashlib.sha256(raw).hexdigest(),
        "tuSha16": hashlib.sha256(raw).hexdigest()[:16],
        "productionBody": {"function": "AttachKind4Production",
                           "definitionLine": body_start + 1 if body_start >= 0 else None,
                           "serializeCallLines": serialize_lines,
                           "captureBeforeLines": capture_before,
                           "captureAfterLines": capture_after,
                           "attachCallLines": attach_lines,
                           "serializeCallCount": len(serialize_lines)},
        "productionEntry": {"function": "EnsureKind4AttachedProduction",
                            "noinlineLine": entry_start + 1 if entry_start >= 0 else None,
                            "callSiteLines": entry_call_lines},
        "cExport": {"symbol": "NdsKind4EnsureAttachedEntry",
                    "dllexportLine": export_start + 1 if export_start >= 0 else None},
        "fixture": {"blockLines": list(fixture_block_lines),
                    "entryCalls": fixture_entry_calls,
                    "forbiddenCalls": fixture_forbidden,
                    "directSerializerCalls": fixture_forbidden.get("SerializeBeforeAfter(", 0),
                    "directProductionBodyCalls": fixture_forbidden.get("AttachKind4Production(", 0),
                    "directProductionEntryCalls": fixture_forbidden.get("EnsureKind4AttachedProduction(", 0)},
    }


def raw_receipt_chain_check(*, receipt_path: Path | str | None = None,
                            verdict_path: Path | str | None = None,
                            tu_path: Path | str | None = None) -> dict:
    """核对**磁盘上的 raw 回执确实由生产入口产出**（G5 真判据，不靠字符串声称）。

    * 回执必须存在且非空（生产序列化调用被破坏时它必须是空/缺失 —— 负控成立）；
    * 回执字段逐项齐备：before/after 旧组件保全 + 新 kind4 wrapper/owner/config；
    * `newKind4.wrapper` 必须等于 **attach 的返回值**（verdict.attachReturn），且该 wrapper 必须真出现在
      `afterRows` 里（`wrapperInAfter=true`）——不是 fixture 塞进回执的常量；
    * `countAfter == countBefore + 1`、`captureCodeBefore/After == 0`（生产读层两次采集都 complete）；
    * 源码接线只作补充（`production_chain_sites` 的 `RAW_SERIALIZATION_CALL_MISSING`）。
    """
    receipt_file = Path(receipt_path) if receipt_path else (REPO_ROOT / RAW_RECEIPT_ARTIFACT)
    verdict_file = Path(verdict_path) if verdict_path else (REPO_ROOT / RAW_VERDICT_ARTIFACT)
    problems: list[str] = []

    def check(condition: bool, name: str) -> None:
        if not condition:
            problems.append(name)

    if not receipt_file.is_file():
        raise AttachSpecError(
            "RAW_RECEIPT_MISSING",
            f"{receipt_file} 不存在：生产序列化调用被破坏时回执必须是空/缺失（负控成立）")
    blob = receipt_file.read_bytes()
    if not blob:
        raise AttachSpecError("RAW_RECEIPT_EMPTY", f"{receipt_file} 是 0 字节：等同回执缺失")
    artifact = {"path": str(receipt_file), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}
    try:
        doc = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AttachSpecError("RAW_RECEIPT_JSON_INVALID",
                              f"{type(error).__name__}: {error}") from None
    if not isinstance(doc, dict):
        raise AttachSpecError("RAW_RECEIPT_JSON_INVALID", "回执不是 JSON object")

    missing = [name for name in RAW_RECEIPT_FIELDS if name not in doc]
    if missing:
        problems.append("RAW_RECEIPT_FIELDS_MISSING:" + ",".join(missing))

    before_rows = doc.get("beforeRows") if isinstance(doc.get("beforeRows"), list) else []
    after_rows = doc.get("afterRows") if isinstance(doc.get("afterRows"), list) else []
    old_rows = (doc.get("oldComponentsPreserved")
                if isinstance(doc.get("oldComponentsPreserved"), list) else [])
    new_kind = doc.get("newKind4") if isinstance(doc.get("newKind4"), dict) else {}
    count_before = doc.get("countBefore") if isinstance(doc.get("countBefore"), int) else None
    count_after = doc.get("countAfter") if isinstance(doc.get("countAfter"), int) else None

    for section, rows in (("beforeRows", before_rows), ("afterRows", after_rows)):
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                problems.append(f"{section}[{index}]_NOT_OBJECT")
                continue
            row_missing = [name for name in RAW_RECEIPT_ROW_FIELDS if name not in row]
            if row_missing:
                problems.append(f"{section}[{index}]_MISSING:" + ",".join(row_missing))
    for index, row in enumerate(old_rows):
        if not isinstance(row, dict):
            problems.append(f"oldComponentsPreserved[{index}]_NOT_OBJECT")
            continue
        row_missing = [name for name in RAW_RECEIPT_OLD_FIELDS if name not in row]
        if row_missing:
            problems.append(f"oldComponentsPreserved[{index}]_MISSING:" + ",".join(row_missing))
        elif row.get("present") is not True:
            problems.append(f"oldComponentsPreserved[{index}]_NOT_PRESERVED")
    missing_new = [name for name in RAW_RECEIPT_NEW_KIND_FIELDS if name not in new_kind]
    if missing_new:
        problems.append("NEW_KIND4_FIELDS_MISSING:" + ",".join(missing_new))

    check(doc.get("phase") == "component_acceptance", "PHASE_NOT_COMPONENT_ACCEPTANCE")
    check(doc.get("code") == "OK", "RECEIPT_CODE_NOT_OK")
    check(doc.get("kind") == KIND_DROP_MOVER, "RECEIPT_KIND_NOT_MOVER")
    check("KIND_OWNER_CLASS_FIELDS_UNRESOLVED" in str(doc.get("evidenceGateGap")),
          "EVIDENCE_GATE_GAP_MISSING")
    check(doc.get("captureCodeBefore") == 0, "CAPTURE_CODE_BEFORE_NOT_COMPLETE")
    check(doc.get("captureCodeAfter") == 0, "CAPTURE_CODE_AFTER_NOT_COMPLETE")
    check(doc.get("owner") == doc.get("oldOwnerBefore") == doc.get("oldOwnerAfter"),
          "OWNER_NOT_UNCHANGED")
    if count_before is None or count_after is None:
        problems.append("COUNT_FIELDS_MISSING")
    else:
        check(count_after == count_before + 1, "COUNT_DELTA_NOT_ONE")
        check(len(before_rows) == count_before and len(after_rows) == count_after,
              "ROW_COUNTS_DISAGREE_WITH_COUNT_FIELDS")
    kind4_rows = [row for row in after_rows if isinstance(row, dict) and row.get("kind") == KIND_DROP_MOVER]
    check(len(kind4_rows) == 1, "NEW_KIND4_ROW_COUNT_NOT_ONE")
    if kind4_rows:
        new_row = kind4_rows[0]
        check(new_kind.get("wrapper") == new_row.get("wrapper"),
              "NEW_KIND4_WRAPPER_NOT_THE_AFTER_ROW")
        check(new_kind.get("config") == new_row.get("config"), "NEW_KIND4_CONFIG_MISMATCH")
        check(new_kind.get("configClass") == new_row.get("configClass"),
              "NEW_KIND4_CONFIG_CLASS_MISMATCH")
        check(new_kind.get("owner") == doc.get("owner"), "NEW_KIND4_OWNER_MISMATCH")
    check(new_kind.get("present") is True, "NEW_KIND4_NOT_PRESENT")
    check(new_kind.get("wrapperInAfter") is True, "NEW_KIND4_WRAPPER_IN_AFTER_FALSE")
    old_expected = [row for row in before_rows
                    if isinstance(row, dict) and row.get("kind") != KIND_DROP_MOVER]
    check(len(old_rows) == len(old_expected), "OLD_COMPONENT_ROW_COUNT_MISMATCH")
    for row in old_expected:
        if not any(old.get("wrapper") == row.get("wrapper") and old.get("kind") == row.get("kind")
                   for old in old_rows if isinstance(old, dict)):
            problems.append(f"OLD_COMPONENT_NOT_LISTED:wrapper={row.get('wrapper')}")

    verdict: dict | None = None
    if not verdict_file.is_file():
        problems.append("CHAIN_VERDICT_MISSING")
    else:
        try:
            loaded = json.loads(verdict_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append("CHAIN_VERDICT_INVALID:" + type(error).__name__)
            loaded = None
        if isinstance(loaded, dict):
            verdict = loaded
        elif loaded is not None:
            problems.append("CHAIN_VERDICT_INVALID:not-an-object")
    if verdict is not None:
        check(verdict.get("ok") is True, "CHAIN_VERDICT_NOT_OK")
        check(verdict.get("receiptBytes") == artifact["bytes"], "VERDICT_RECEIPT_BYTES_MISMATCH")
        check(verdict.get("attachCalls") == 1, "ATTACH_NOT_CALLED_EXACTLY_ONCE")
        check(verdict.get("attachKind") == KIND_DROP_MOVER, "ATTACH_KIND_NOT_MOVER")
        check(verdict.get("attachReturn") == new_kind.get("wrapper"),
              "WRAPPER_NOT_FROM_ATTACH_RETURN")
        check(verdict.get("wrapperFromAttachReturn") is True, "WRAPPER_IDENTITY_NOT_FROM_ATTACH")
        check(verdict.get("liveGameAttachExecuted") is False,
              "LIVE_ATTACH_CLAIMED_IN_OFFLINE_FIXTURE")
        check(verdict.get("countBefore") == count_before and verdict.get("countAfter") == count_after,
              "VERDICT_COUNTS_MISMATCH")
        check(verdict.get("captureCodeBefore") == 0 and verdict.get("captureCodeAfter") == 0,
              "VERDICT_CAPTURE_CODE_NOT_COMPLETE")
        check(verdict.get("receiptCode") == "OK", "VERDICT_RECEIPT_CODE_NOT_OK")
        check(verdict.get("phase") == "component_acceptance", "VERDICT_PHASE_MISMATCH")

    sites = production_chain_sites(tu_path)
    if not sites.get("ok"):
        problems.append("SOURCE_CHAIN:" + str(sites.get("code")))

    return {
        "ok": not problems,
        "code": "RAW_RECEIPT_CHAIN_OK" if not problems else "RAW_RECEIPT_CHAIN_BROKEN",
        "problems": problems,
        "artifact": artifact,
        "receiptFields": {
            "topLevel": list(RAW_RECEIPT_FIELDS),
            "topLevelPresent": [name for name in RAW_RECEIPT_FIELDS if name in doc],
            "artifactOrder": list(doc.keys()),
            "rows": list(RAW_RECEIPT_ROW_FIELDS),
            "oldComponent": list(RAW_RECEIPT_OLD_FIELDS),
            "newKind4": list(RAW_RECEIPT_NEW_KIND_FIELDS),
        },
        "newKind4": dict(new_kind),
        "counts": {"before": count_before, "after": count_after},
        "verdict": {
            "path": str(verdict_file),
            "ok": verdict.get("ok") if verdict else None,
            "attachReturn": verdict.get("attachReturn") if verdict else None,
            "wrapperFromAttachReturn": verdict.get("wrapperFromAttachReturn") if verdict else None,
        },
        "sourceChain": sites,
        "note": ("回执字节由生产入口产出（fixture 只把生产 sink 落盘）；源码检查器只是补充，不能替代调用链。"
                 "破坏生产调用时回执必须为空/缺失（见 .life-dropstuff-out/g5-chain/ 的负控产物）。"),
    }


def verify_production_serialization_call(tu_path: Path | str | None = None) -> dict:
    """**生产序列化调用检查器**（离线可核）：`AttachKind4Production` 函数体内必须真的调用
    `SerializeBeforeAfter(`；缺失即 **`RAW_SERIALIZATION_CALL_MISSING`**（破坏副本必须失败）。

    为什么需要它：fixture 自己也会调序列化器（`:349`），所以“编得过 + 有产物”**不能**证明生产调用在位；
    这个检查器只看**生产函数体内**那一次调用。
    """
    path = Path(tu_path) if tu_path else (REPO_ROOT / "tools/mondstadt/life/dropstuff/native/native_dropstuff.cpp")
    if not path.is_file():
        return {"ok": False, "code": "TU_MISSING", "tu": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if "AttachKind4Production(" in line and "ProdReceipt" in line:
            start = index
            break
    if start is None:
        return {"ok": False, "code": "PRODUCTION_FUNCTION_NOT_FOUND", "tu": str(path)}
    depth = 0
    body: list[tuple[int, str]] = []
    opened = False
    for index in range(start, len(lines)):
        line = lines[index]
        depth += line.count("{") - line.count("}")
        if not opened and "{" in line:
            opened = True
        if opened:
            body.append((index + 1, line))
        if opened and depth <= 0:
            break
    calls = [{"line": number, "code": code.strip()[:100]}
             for number, code in body if "SerializeBeforeAfter(" in code]
    return {"ok": bool(calls), "code": "RAW_SERIALIZATION_CALL_PRESENT" if calls else
            "RAW_SERIALIZATION_CALL_MISSING",
            "tu": str(path), "tuBytes": path.stat().st_size,
            "functionStartLine": start + 1, "bodyLines": len(body),
            "productionCalls": calls,
            "note": "只认 `AttachKind4Production` 函数体内的调用；fixture 里的调用不算"}


def _load_shared_contract():
    """按**路径**加载共享契约模块（目录名 `native-card` 带连字符，不能当包 import）。"""
    import importlib.util

    path = REPO_ROOT / SHARED_CONTRACT_MODULE
    spec = importlib.util.spec_from_file_location("_dsh_native_card_dispatch", path)
    if spec is None or spec.loader is None:
        raise AttachSpecError("SHARED_CONTRACT_UNREADABLE", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def invoke_shared_component_contract(*, source: str, built: dict | None = None,
                                     fresh: bool = False) -> dict:
    """**真调共享 `component_prepared` / `component_acceptance`**（不是字符串判定）。

    * 真 import `tools/editor-bridge/native-card/dispatch.py`；
    * 传真实参数（`tool='mondstadt-dropstuff'`、候选目录路径、`build-result.json`）；
    * **原样记录**对方返回的 dict 或它抛出的具名拒绝码 —— 不掩盖、不美化。
    """
    source_path = Path(source)
    if not source_path.is_dir():
        return {"called": False, "code": "SOURCE_DIR_MISSING", "source": str(source_path)}
    module = _load_shared_contract()
    built_doc = dict(built or {})
    if not built_doc and (source_path / "build-result.json").is_file():
        try:
            built_doc = json.loads((source_path / "build-result.json").read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001
            return {"called": False, "code": "BUILT_DOC_UNREADABLE",
                    "detail": f"{type(error).__name__}: {error}"[:200]}
    record: dict = {"called": True, "tool": SHARED_CONTRACT_TOOL,
                    "module": SHARED_CONTRACT_MODULE, "source": str(source_path)}
    prepared: dict | None = None
    try:
        prepared = module.component_prepared(SHARED_CONTRACT_TOOL, source_path, built_doc, fresh=fresh)
        record["prepared"] = {"ok": True, "kind": prepared.get("kind")}
    except Exception as error:  # noqa: BLE001 - 共享契约的具名拒绝，原样带出
        record["prepared"] = {"ok": False, "code": getattr(error, "code", None) or str(error)[:160]}
        record["stoppedAt"] = "component_prepared"
        return record
    try:
        native = module.component_acceptance(SHARED_CONTRACT_TOOL, source_path, prepared)
        record["acceptance"] = {"ok": True,
                                "mutationVerified": native.get("mutationVerified"),
                                "prefixPreserved": native.get("prefixPreserved"),
                                "configurationVerified": native.get("configurationVerified")}
    except Exception as error:  # noqa: BLE001
        record["acceptance"] = {"ok": False, "code": getattr(error, "code", None) or str(error)[:160]}
        record["stoppedAt"] = "component_acceptance"
    return record


def compile_check(run_dir: Path, *, vcvars: str | None = None, timeout_s: int = 900) -> dict:
    """编译一次性目录里的固定源码（含隔离共享层）→ layout probe → wrapper --dry → 独立解码。"""
    run = Path(run_dir)
    if not (run / "run.json").is_file():
        raise AttachSpecError("RUN_DIR_INVALID", f"{run} 里没有 run.json（先用 --prepare 生成）")
    meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
    vcv = vcvars or ("C:\\Program Files\\Microsoft Visual Studio\\2022\\Community"
                     "\\VC\\Auxiliary\\Build\\vcvars64.bat")
    script = run / "build" / "build.cmd"
    result: dict = {"ok": False, "runDir": str(run), "vcvars": vcv, "gameDispatch": False,
                    "commands": [], "layout": None, "rawLog": None, "configGateLog": None,
                    "accept": None, "configGateAccept": None}
    build = subprocess.run(f'"{script}" "{run}" "{vcv}"', shell=True, capture_output=True,
                           text=True, timeout=timeout_s)
    result["commands"].append({"cmd": f'"{script}" "{run}" "{vcv}"', "returncode": build.returncode,
                               "stdoutTail": build.stdout.strip().splitlines()[-2:],
                               "stderrTail": build.stderr.strip().splitlines()[-2:]})
    if build.returncode != 0:
        result["code"] = "COMPILE_FAILED"
        return result
    layout_exe = run / "build" / "dropstuff_layout.exe"
    layout = subprocess.run([str(layout_exe)], capture_output=True, text=True, timeout=120)
    result["commands"].append({"cmd": str(layout_exe), "returncode": layout.returncode,
                               "stdout": layout.stdout.strip()})
    if layout.returncode != 0:
        result["code"] = "LAYOUT_PROBE_FAILED"
        return result
    layout_doc = json.loads(layout.stdout.strip())
    result["layout"] = layout_doc
    missing = [key for key in REQUIRED_LAYOUT_KEYS if key not in layout_doc]
    if missing:
        result["code"] = "LAYOUT_KEYS_MISSING"
        result["missingLayoutKeys"] = missing
        return result
    if (layout_doc["action"] != ACTION_CODE or layout_doc["protocol"] != RECEIPT_VERSION
            or layout_doc["kindString"] != kind_string_for(_ACTIVE_KIND)):
        result["code"] = "LAYOUT_CONSTANTS_MISMATCH"
        return result

    wrapper = run / "build" / "dropstuff_wrapper.exe"
    dry = subprocess.run([str(wrapper), "--dry"], capture_output=True, text=True, timeout=120)
    result["commands"].append({"cmd": f"{wrapper} --dry", "returncode": dry.returncode,
                               "stdout": dry.stdout.strip()})
    result["rawLog"] = dry.stdout.strip()
    try:
        result["accept"] = accept_raw_log(dry.stdout, meta)
    except AttachSpecError as error:
        result["code"] = error.code
        result["accept"] = error.as_dict()
        return result

    gate = subprocess.run([str(wrapper), "--dry", "--config-unknown"], capture_output=True,
                          text=True, timeout=120)
    result["commands"].append({"cmd": f"{wrapper} --dry --config-unknown",
                               "returncode": gate.returncode, "stdout": gate.stdout.strip()})
    result["configGateLog"] = gate.stdout.strip()
    try:
        result["configGateAccept"] = accept_raw_log(gate.stdout, meta, accept_config_refusal=True)
    except AttachSpecError as error:
        result["code"] = error.code
        result["configGateAccept"] = error.as_dict()
        return result

    disabled = subprocess.run([str(wrapper)], capture_output=True, text=True, timeout=120)
    result["commands"].append({"cmd": str(wrapper), "returncode": disabled.returncode,
                               "stdout": disabled.stdout.strip()})
    result["dispatchDisabled"] = "GAME_DISPATCH_DISABLED_IN_DEV" in disabled.stdout

    result["ok"] = bool(result["accept"]["ok"] and result["configGateAccept"]["ok"]
                        and result["dispatchDisabled"])
    result["code"] = "COMPILE_CHECK_OK" if result["ok"] else "ACCEPT_REFUSED"
    return result


# ---------------------------------------------------------------------------
# 8. 规格 / 判决 / 回执
# ---------------------------------------------------------------------------


def native_profile(*, build_sha256: str = "", derived_utc: str = "") -> dict:
    target = build_target_config()
    return {
        "schemaVersion": 3, "profileId": "dropstuff-kind37-native-profile-v3",
        "kindString": KIND_STRING, "actionCode": ACTION_CODE, "receiptProtocol": RECEIPT_VERSION,
        "target": {"image": target.get("targetImage"), "source": TOOLCHAIN["targetImageSource"],
                   "imageExists": target.get("targetImageExists"),
                   "imageBytes": target.get("targetImageBytes"),
                   "profileVerified": target.get("profileVerified"),
                   "imageObserved": target.get("imageObserved"),
                   "hotfixRvas": target.get("hotfixRvas"),
                   "actionRegisteredInProfile": target.get("actionRegisteredInProfile"),
                   "oldWrongTarget": "BeyondEditor.dll（revision ≤6 的错误目标，本版已修）"},
        "build": {"sha256": build_sha256 or None, "derivedUtc": derived_utc or None},
        "attachAbi": dict(ATTACH_ABI), "readLayer": dict(READ_LAYER),
        "executableKinds": list(EXECUTABLE_KINDS),
        "runLedger": {str(k): v for k, v in KIND_RUN_LEDGER.items()},
        "hostLimitPerRequest": 4, "gameDispatch": False,
        "preparedRoot": PREPARED_ROOT.as_posix(),
        "refusals": target.get("refusals", []),
    }


@dataclass(frozen=True)
class DictRuntimePlan:
    nodeId: int
    pinName: str
    entries: tuple
    keyListPayload: dict
    valueListPayload: dict
    refusals: tuple = ()
    pinnable: bool = False

    def as_dict(self) -> dict:
        return {"approach": "runtime-construct（1088/1788）", "nodeId": self.nodeId,
                "pinName": self.pinName, "entryCount": len(self.entries),
                "keyList": self.keyListPayload, "valueList": self.valueListPayload,
                "keyListDigest": canonical_json_digest(self.keyListPayload),
                "valueListDigest": canonical_json_digest(self.valueListPayload),
                "refusals": list(self.refusals), "pinnable": self.pinnable,
                "whyNotPinnable": [r["code"] for r in self.refusals], "writesGameBytes": False}


def canonical_json_digest(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_dict_recipe_facts() -> dict:
    if not RECIPES_PATH.is_file():
        raise AttachSpecError("recipes_missing", f"没找到 {RECIPES_PATH}")
    records = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    by_id: dict[int, dict] = {}
    for record in records:
        tail = str(record.get("definitionKey", "")).rsplit(":", 1)[-1]
        if tail.isdigit():
            by_id[int(tail)] = record
    for node_id in (BUILD_DICT_NODE, ASSEMBLE_DICT_NODE):
        if node_id not in by_id:
            raise AttachSpecError("node_missing", f"recipes.json 里没有 definitionId {node_id}")

    def facts(node_id: int) -> dict:
        record = by_id[node_id]
        trees = sorted({m.get("treeId") for m in record.get("availableInMenus") or []
                        if isinstance(m.get("treeId"), int)})
        return {"definitionKey": record.get("definitionKey"), "name": record.get("name"),
                "classicTreeId12": 12 in trees,
                "ports": [(p["key"], p.get("name"), (p.get("signature") or {}).get("serverParamType"),
                           (p.get("signature") or {}).get("genericId"))
                          for p in record.get("ports") or []],
                "dynamicPortsRaw": (record.get("dynamicPorts") or {}).get("raw")}

    raw_inputs = by_id[BUILD_DICT_NODE].get("inputs") or []
    choice = None
    if raw_inputs and raw_inputs[0].get("choices"):
        first = raw_inputs[0]["choices"][0]
        descriptor = first["descriptor"]
        members = first.get("containerMembers") or descriptor.get("containerMembers") or []
        choice = {"choiceIndex": first["choiceIndex"], "storageKind": descriptor.get("storageKind"),
                  "genericId": descriptor.get("genericId"),
                  "serverParamType": descriptor.get("serverParamType"),
                  "containerMembers": [{"field": m.get("field"),
                                        "storageKind": (m.get("descriptor") or {}).get("storageKind"),
                                        "genericId": (m.get("descriptor") or {}).get("genericId")}
                                       for m in members]}
    pairs = [p for p in by_id[ASSEMBLE_DICT_NODE].get("ports") or []
             if str(p.get("name", "")).startswith("键")]
    return {"buildDict": facts(BUILD_DICT_NODE), "assembleDict": facts(ASSEMBLE_DICT_NODE),
            "buildKeyListChoice": choice, "assemblePairCount": len(pairs),
            "sinkPins": {str(k): {"portIndex": v[0], "name": v[1]} for k, v in DICT_SINK_NODES.items()},
            "allClassic": bool(facts(BUILD_DICT_NODE)["classicTreeId12"]
                               and facts(ASSEMBLE_DICT_NODE)["classicTreeId12"])}


def dict_runtime_plan(item_counts: dict, *, node_id: int = BUILD_DICT_NODE,
                      pin_name: str | None = None) -> DictRuntimePlan:
    if node_id not in (BUILD_DICT_NODE, ASSEMBLE_DICT_NODE):
        raise AttachSpecError("unsupported_dict_node", f"只支持 {BUILD_DICT_NODE} / {ASSEMBLE_DICT_NODE}")
    facts = verify_dict_recipe_facts()
    pairs = []
    for item_id, count in item_counts.items():
        if type(item_id) is not int or item_id <= 0:
            raise AttachSpecError("bad_item_config_id", f"道具配置ID 必须是正整数：{item_id!r}")
        if type(count) is not int or count == 0:
            raise AttachSpecError("bad_item_count", f"数量必须是非零整数：{count!r}")
        pairs.append((item_id, count))
    if not pairs:
        raise AttachSpecError("empty_dict_not_enough", "空字典不算完成泛型实例化（资源 warning 逐字）")
    if node_id == ASSEMBLE_DICT_NODE and len(pairs) > facts["assemblePairCount"]:
        raise AttachSpecError("assemble_pair_limit_exceeded",
                              f"{ASSEMBLE_DICT_NODE} 只有 {facts['assemblePairCount']} 对槽")
    raw = json.dumps(facts["assembleDict"]["dynamicPortsRaw"], ensure_ascii=False)[:160]
    refusals = (
        {"code": "DICT_GENERIC_MATERIALIZATION_UNVERIFIED",
         "detail": "1088 的键/值端口都是泛型；连上具体类型后的物化结果从未上机观测"},
        {"code": "DICT_DYNAMIC_PORT_LIMIT_UNVERIFIED",
         "detail": f"dynamicPorts.raw 只给字面量 100 与步长字段（raw={raw}）"},
        {"code": "DICT_GENERIC_CHOICE_INDEX_UNPINNED",
         "detail": "choices[0] 只是资源顺序；author CLI 没有选择泛型端点的入口"},
    )
    return DictRuntimePlan(nodeId=node_id, pinName=pin_name or "战利品掉落字典",
                           entries=tuple(pairs),
                           keyListPayload={"list": [{"uint": i} for i, _ in pairs]},
                           valueListPayload={"list": [{"int": n} for _, n in pairs]},
                           refusals=refusals, pinnable=False)


def attach_verdicts(requests: Sequence[AttachRequest], anchors: BuildAnchors | None) -> list[dict]:
    out = []
    for req in requests:
        entry = {"ref": req.entity_ref, "entityId": req.entity_id, "kind": req.kind,
                 "kindMember": component_kind_name(req.kind), "runLedger": KIND_RUN_LEDGER[req.kind],
                 "nativeWritePerformed": False}
        if anchors is None:
            entry["verdict"] = "BLOCKED"
            entry["code"] = "ABI_ANCHOR_NOT_DERIVED"
        else:
            entry["verdict"] = "EXECUTABLE"
            entry["route"] = "--prepare 的一次性候选目录（hook/wrapper/probe）+ --compile-check"
        out.append(entry)
    return out


def receipt(level_id: int, verdicts: Sequence[dict], *, batches: dict | None = None,
            writes: int = 0) -> str:
    return json.dumps({
        "receiptVersion": 3, "kindString": KIND_STRING, "actionCode": ACTION_CODE,
        "receiptProtocol": RECEIPT_VERSION, "levelId": level_id,
        "nativeWritePerformed": writes > 0, "executedNothing": writes == 0,
        "verdicts": list(verdicts), "batches": batches,
        "whyNoWrites": "开发期所有游戏派发关闭；由 root 在统一阶段对接 native-card route。",
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 9. 自检 + CLI
# ---------------------------------------------------------------------------


def chain_selfcheck(artifacts: dict[str, str]) -> dict:
    problems: list[str] = []
    for name, text in artifacts.items():
        if name.endswith((".h", ".cpp")):
            for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
                if text.count(opener) != text.count(closer):
                    problems.append(f"{name}: {opener}{closer} 不配平")
        if name == "hook/dropstuff_kind37.cpp":
            for token in ("EnsureComponentAttached", "ReadRowsFn", "native_tabs", "generalized_tabs"):
                if token in text:
                    problems.append(f"{name}: 出现禁项 {token}")
    source = artifacts.get("hook/dropstuff_kind37.cpp", "")
    return {
        "ok": not problems, "files": sorted(artifacts), "problems": problems,
        "reusesSharedReadLayer": "CaptureComponents" in source,
        "doesNotCallSharedWhitelist": "EnsureComponentAttached" not in source,
        "wrapperIdentityCheck": "wrapper_identity_mismatch" in source,
        "twoArgumentAttach": "attach(reinterpret_cast<void*>(owner), DS_KIND)" in source,
        "onlyKind37Allowed": "kind == DS_KIND" in source,
        "configFieldGate": "config_field_unknown" in source,
        "rawAcceptIndependent": "probe::CaptureComponents" in source,
        "configCollector": "DumpRowConfig" in source,
        "fixedWrapper": "GAME_DISPATCH_DISABLED_IN_DEV" in artifacts.get("wrapper/dropstuff_wrapper.cpp", ""),
        "byteSizes": {name: len(text.encode("utf-8")) for name, text in sorted(artifacts.items())},
    }


def selftest() -> dict:
    source = open(__file__, encoding="utf-8").read()
    compile(source, __file__, "exec")          # 判据：Python compile()
    checks: dict = {"pythonCompile": True}
    checks["rowRoundtrip"] = row_roundtrip_selftest()
    files = emit_toolchain_files(nonce=12345, deadline_tick=0, target_config=build_target_config())
    checks["toolchainFiles"] = chain_selfcheck(files)
    checks["profile"] = native_profile()
    checks["configCollection"] = {k: v for k, v in config_collection_plan().items()
                                  if k in ("approach", "targetKindConfigField", "fieldSources",
                                           "writeSideGate")}
    checks["dict"] = {"facts": {k: v for k, v in verify_dict_recipe_facts().items()
                                if k in ("buildKeyListChoice", "assemblePairCount", "allClassic")},
                      "plan1088": dict_runtime_plan({1: 1}, node_id=1088).as_dict()}
    sample_raw = ('DSRAW1 {"status":"ok","kind":37,"action":20,"protocol":25,"nonce":12345,'
                  '"attachCode":"ok","acceptCode":"ok","wrapperIdentity":1,"readbackVerified":1,'
                  '"sourceBefore":"hook::EnsureDropStuffAttached",'
                  '"sourceAfter":"probe::CaptureComponents","configField":0,"configFieldSource":0,'
                  '"configWritten":0,"snapshotRowsBefore":1,"snapshotRowsAfter":2,"tick":1}')
    checks["rawDecodeSelfTest"] = accept_raw_log(sample_raw, {"nonce": 12345})
    refusals = {}
    for name, fn in (
        ("kind17Refused", lambda: require_executable_kind(17)),
        ("configField37", lambda: config_field_for_kind(KIND_DROP_STUFF)),
        ("candidateDirReuse", lambda: prepare_candidate_dir(
            out_dir=Path(__file__).resolve().parent, run_id=".", nonce=1)),
        ("batchIntersection", lambda: plan_attach_batches(
            [AttachRequest("t1", 1077936130), AttachRequest("t1", 1077936130)], max_per_batch=2)),
        ("sameSourceProof", lambda: verify_attach_receipt({
            "beforeSource": "a", "afterSource": "a",
            "diff": {"addedRows": [{"kind": 37}], "changedRows": []}})),
        ("rawMarker", lambda: decode_raw_receipt("NOT-A-RAW-LINE")),
        ("emptyDict", lambda: dict_runtime_plan({}, node_id=1088)),
        ("rawNonceMismatch", lambda: accept_raw_log(sample_raw, {"nonce": 999})),
    ):
        try:
            fn()
            refusals[name] = None
        except (AttachSpecError, OSError) as error:
            refusals[name] = getattr(error, "code", type(error).__name__)
    checks["refusals"] = refusals
    checks["allRefusalsFired"] = all(v is not None for v in refusals.values())
    checks["ok"] = bool(checks["pythonCompile"] and checks["rowRoundtrip"]["ok"]
                        and checks["toolchainFiles"]["ok"] and checks["allRefusalsFired"]
                        and checks["rawDecodeSelfTest"]["accepted"])
    return checks


def _main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command = argv[0]
    if command == "--selftest":
        result = selftest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if command == "--prepare":
        out = None
        run_id = None
        session: dict = {}
        for index, token in enumerate(argv):
            if token == "--out" and index + 1 < len(argv):
                out = Path(argv[index + 1])
            if token == "--run-id" and index + 1 < len(argv):
                run_id = argv[index + 1]
            # 显式 fixture session（编译候选用；run.json.sessionBound 会如实标注，绝不用于 launchable）
            if token == "--session-pid" and index + 1 < len(argv):
                session["pid"] = int(argv[index + 1])
            if token == "--session-tid" and index + 1 < len(argv):
                session["tid"] = int(argv[index + 1])
            if token == "--session-creation" and index + 1 < len(argv):
                session["processCreation"] = int(argv[index + 1])
            if token == "--session-thread" and index + 1 < len(argv):
                session["threadCreation"] = int(argv[index + 1])
            if token == "--session-image" and index + 1 < len(argv):
                session["image"] = argv[index + 1]
        try:
            report = prepare_candidate_dir(out_dir=out, run_id=run_id,
                                           session=(session or None))
        except AttachSpecError as error:
            print(json.dumps(error.as_dict(), ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if command == "--compile-check":
        # **兼容 `--run <DIR>` / `--run=<DIR>` 写法**：此前只认位置参数，`--run <dir>` 会被当成不存在的
        # 路径 ⇒ RUN_DIR_INVALID（而该目录里确实有 run.json）。
        rest = [token for token in argv[1:] if token not in ("--run", "--run-dir")]
        rest = [token.split("=", 1)[1] if token.startswith("--run=") else token for token in rest]
        run_dir_arg = rest[0] if rest else ""
        if not run_dir_arg:
            print("用法: --compile-check <RUN_DIR> [VCVARS64]")
            return 2
        try:
            report = compile_check(Path(run_dir_arg), vcvars=(rest[1] if len(rest) > 1 else None))
        except AttachSpecError as error:
            print(json.dumps(error.as_dict(), ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1
    if command == "--print-spec":
        print(json.dumps({"ok": True, "toolchain": TOOLCHAIN, "profile": native_profile(),
                          "configCollection": config_collection_plan()}, ensure_ascii=False, indent=2))
        return 0
    if command == "--chain-sites":
        # **补充**的源码接线检查（RAW_SERIALIZATION_CALL_MISSING 在这里；不替代实际调用链）。
        try:
            sites = production_chain_sites(argv[1] if len(argv) > 1 else None)
        except AttachSpecError as error:
            print(json.dumps(error.as_dict(), ensure_ascii=False))
            return 1
        print(json.dumps(sites, ensure_ascii=False, indent=2))
        return 0 if sites["ok"] else 1
    if command == "--chain-check":
        # G5 真判据：磁盘 raw 回执 + fixture verdict + TU 接线。用法：
        #   --chain-check [RECEIPT] [VERDICT] [TU]（缺省用 .life-dropstuff-out/ 下的两份产物）
        args = [token for token in argv[1:] if token not in ("--",)]
        try:
            report = raw_receipt_chain_check(
                receipt_path=args[0] if len(args) > 0 else None,
                verdict_path=args[1] if len(args) > 1 else None,
                tu_path=args[2] if len(args) > 2 else None,
            )
        except AttachSpecError as error:
            print(json.dumps(error.as_dict(), ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if command == "--receipt":
        level = int(argv[1]) if len(argv) > 1 else 1073741843
        reqs = [AttachRequest(f"host{i}", 1077936130 + i) for i in range(2)]
        print(receipt(level, attach_verdicts(reqs, None), batches=plan_attach_batches(reqs)))
        return 0
    print(f"未知命令 {command!r}（支持 --prepare / --compile-check / --selftest / --print-spec / "
          f"--receipt / --chain-sites / --chain-check）")
    return 2


# ---------------------------------------------------------------------------
# revision 9 追加：transport 卡片层（caller 给目录 + baseline 双分支 + executed 语义）
# ---------------------------------------------------------------------------

TRANSPORT_BUILD_KIND = KIND_STRING                                  # mondstadt-dropstuff-build-v1
TRANSPORT_PREPARED_KIND = KIND_STRING.replace("-build-", "-prepared-")
TRANSPORT_SCOPE = "FIXED_MONDSTADT_DROPSTUFF_ACTION"     # 对齐 native-card/dispatch.py:44 的路由
DISPATCH_ROUTE_PATH = REPO_ROOT / "tools" / "editor-bridge" / "native-card" / "dispatch.py"
ACCEPTOR_RELATIVE = "tools/mondstadt/life/dropstuff/native_acceptance.py"


def _ensure_utf8_io() -> None:
    """入口把 stdout/stderr 设成 UTF-8（默认 GBK 环境下打 ``⇒`` 会 UnicodeEncodeError）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover - 只读流等极端情况
                pass


def _transport_route() -> dict:
    """只读解析 ``native-card/dispatch.py`` 里 mondstadt-dropstuff 的固定路由。

    ``component_prepared`` 要求 actionCode/receiptVersion/levelId/scope/wrapperName 与路由**逐键一致**
    （dispatch.py:158-161），所以 wrapper 名字与 scope 都不猜，直接取路由；取不到即具名拒绝。
    """
    if not DISPATCH_ROUTE_PATH.is_file():
        raise AttachSpecError("TRANSPORT_ROUTE_MISSING", str(DISPATCH_ROUTE_PATH))
    text = DISPATCH_ROUTE_PATH.read_text(encoding="utf-8")
    level = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("LEVEL") and "=" in stripped:
            try:
                level = int(stripped.split("=", 1)[1].strip().rstrip(","))
            except ValueError:
                level = None
    index = text.find("FIXED_MONDSTADT_DROPSTUFF_ACTION")
    if index < 0:
        raise AttachSpecError("TRANSPORT_ROUTE_NOT_FOUND", "dispatch.py 里没有 mondstadt-dropstuff 路由")
    # 路由项跨两行（kind/wrapper 一行、scope/action/protocol 一行）⇒ 只取该行前后各一小段；
    # 不做 ±400 字符窗口（那会把上一条路由的 action/protocol 也吞进来，实测得到 13/18）。
    lines = text.splitlines()
    scope_line = next(i for i, line in enumerate(lines)
                      if "FIXED_MONDSTADT_DROPSTUFF_ACTION" in line)
    window = "\n".join(lines[max(0, scope_line - 1):scope_line + 4])
    route: dict = {}
    for key in ("action", "protocol", "scope", "wrapper"):
        marker = key + "="
        at = window.find(marker)
        if at < 0:
            continue
        value = window[at + len(marker):].split(",", 1)[0].split(")", 1)[0].strip()
        route[key] = value.strip("'\"")
    for key in ("action", "protocol"):
        if key in route:
            route[key] = int(route[key])
    if "scope" not in route or "wrapper" not in route:
        raise AttachSpecError("TRANSPORT_ROUTE_INCOMPLETE", f"窗口内只解析到 {sorted(route)}")
    route["levelId"] = level if level is not None else 1073741843
    return route
#: `hashes` 必须齐的八项（owner 口径 2）。
REQUIRED_HASH_KEYS = ("target_config.h", "baseline-snapshot.bin", "normalized-spec.json",
                      "receipt-layout.json", "hook_receipt.dll", "hook_receipt_probe.exe")


def required_hash_keys(route: dict) -> tuple:
    """hashes 八项的键名**由 route 派生**（wrapper 名不许写死；dispatch.py:43 / :226）。"""
    return REQUIRED_HASH_KEYS + (str(route["wrapper"]), "prepared.json")


def run_probe(probe_exe, *args, timeout_s: int = 180) -> dict:
    """**真实调用** probe 可执行体（生产链里 wrapper 走同一条命令形状）。

    可执行体缺失即具名拒绝 ``PROBE_MISSING``，不静默跳过。
    """
    exe = Path(probe_exe)
    if not exe.is_file():
        raise AttachSpecError("PROBE_MISSING", str(exe))
    done = subprocess.run([str(exe), *[str(a) for a in args]], capture_output=True, text=True,
                          timeout=timeout_s)
    return {"ok": done.returncode == 0, "exitCode": done.returncode, "stdout": done.stdout}


def decode_run_verdict(run_dir) -> dict:
    """**实际调用** ``build_readonly_profile.decode_run(run)`` 判定 baseline（#4）。

    caller 只能给目录；判定由 ro 的独立解码给出（与 dispatch.py:169 的 baseline 绑定同源）。
    """
    if not run_dir:
        return {"ok": False, "code": "REAL_BASELINE_REQUIRES_RUNNING_TARGET"}
    try:
        _load_native_profiles()                      # 把 tools/game-executor 放进 sys.path
        import importlib
        module = importlib.import_module("build_readonly_profile")
        return {"ok": True, "decoded": module.decode_run(Path(run_dir))}
    except Exception as error:
        return {"ok": False, "code": "DECODE_RUN_FAILED",
                "detail": f"{type(error).__name__}: {error}"}


def normalized_spec(*, level_id: int = 1073741843, hosts: Sequence[int] = (),
                    mutation: dict | None = None, configuration: dict | None = None,
                    kind: int | None = None) -> dict:
    """业务 spec（**必须先校验**再进卡片；缺件即具名拒绝）。

    **kind4 分支**：走**模块私有** config 路径（`config_collection_plan()`），**不要求 kind37 的单字段号**
    （`config_field_for_kind(4)` 已具名 `config_field_unknown`）；拿不到即**具名拒绝**，不静默。
    """
    active_kind = require_executable_kind(int(kind) if kind is not None else KIND_DROP_STUFF)
    config_plan: dict = {}
    if active_kind == KIND_DROP_MOVER:
        try:
            config_plan = dict(config_collection_plan() or {})
        except Exception as error:  # noqa: BLE001
            raise AttachSpecError("KIND4_CONFIG_PLAN_UNAVAILABLE", str(error)[:200]) from None
        if not config_plan:
            raise AttachSpecError("KIND4_CONFIG_PLAN_UNAVAILABLE",
                                  "config_collection_plan() 为空：kind4 无可用 config 收集面")
    if int(level_id) != 1073741843:
        raise AttachSpecError("spec_level_not_bound", f"levelId={level_id}（本卡固定 1073741843）")
    host_list = [int(host) for host in hosts]
    if not host_list:
        raise AttachSpecError("spec_hosts_empty", "hosts 为空")
    for host in host_list:
        if not 1 <= host <= 4294967295:
            raise AttachSpecError("host_out_of_uint32", f"宿主 id {host}")
    spec = {"levelId": int(level_id), "actionCode": ACTION_CODE, "receiptVersion": RECEIPT_VERSION,
            "kind": active_kind, "scope": TRANSPORT_SCOPE, "hosts": host_list,
            "configPlan": config_plan, "configFieldKnown": not (active_kind == KIND_DROP_MOVER),
            "mutation": dict(mutation or {"declared": True, "addedCount": 1}),
            "configuration": dict(configuration or {"expected": {}})}
    if not spec["configuration"].get("expected"):
        raise AttachSpecError("spec_configuration_not_declared",
                              "configuration.expected 必须给出 kind37 词表的期望值（否则验收器会拒）")
    return spec


LAYOUT_JSON_PATH = Path(__file__).resolve().parent / "receipt-layout.json"


def layout_from_probe(layout_path: Path | None = None) -> dict:
    """layout **来自编译期 probe 的真实产物**（``receipt-layout.json``，含 sizeof_*/offsetof_*）。

    文件缺失或缺少编译期键 ⇒ 具名拒绝（``LAYOUT_PROBE_ARTIFACT_MISSING`` /
    ``LAYOUT_PROBE_KEY_MISSING``），不再退回声明式默认参数。
    """
    path = Path(layout_path) if layout_path else LAYOUT_JSON_PATH
    if not path.is_file():
        raise AttachSpecError("LAYOUT_PROBE_ARTIFACT_MISSING", str(path))
    document = json.loads(path.read_text(encoding="utf-8"))
    probe = document.get("probe") or {}
    for key in ("sizeof_Result", "offsetof_Result_before_count", "offsetof_Result_after_count",
                "sizeof_ConfigWritePlan", "sizeof_ConfigDump", "configDumpBytes"):
        if key not in probe:
            raise AttachSpecError("LAYOUT_PROBE_KEY_MISSING", f"{path}: probe.{key}")
    layout = {
        "source": str(path),
        "compiled": True,
        "probe": dict(probe),
        "receipt": dict(document.get("receipt") or {}),
        "snapshot": dict(document.get("snapshot") or {}),
        "components": dict(document.get("components") or {}),
        "kind37Config": dict(document.get("kind37Config") or {}),
        "sizeof_Result": int(probe["sizeof_Result"]),
        "offsetof_Result_before_count": int(probe["offsetof_Result_before_count"]),
        "offsetof_Result_after_count": int(probe["offsetof_Result_after_count"]),
        "sizeof_ConfigDump": int(probe["sizeof_ConfigDump"]),
        "configDumpBytes": int(probe["configDumpBytes"]),
    }
    for section in ("receipt", "snapshot", "components", "kind37Config"):
        if not layout[section]:
            raise AttachSpecError("LAYOUT_PROBE_SECTION_MISSING", f"{path}: {section}")
    return layout


def layout_from_probe_legacy(*, snapshot_offset: int = 64, snapshot_length: int = 64,
                             receipt_size: int = 320) -> dict:
    """给验收器用的 layout 声明（真实布局到位后**补声明**，语义不放宽）。"""
    return {
        "receipt": {"magic": 0, "version": 4, "nonce": 8, "deadline": 16},
        "snapshot": {"offset": int(snapshot_offset), "length": int(snapshot_length)},
        "raw": {"snapshotHexLength": int(receipt_size)},
        "components": {"beforeOffset": 128, "beforeRows": 2, "afterOffset": 192, "afterRows": 3,
                       "stride": 20, "kind": 0, "entityId": 4, "itemId": 8, "count": 12,
                       "trigger": 16},
        "kind37Config": {"kind": 272, "kindSize": 4, "entityId": 276, "entityIdSize": 4,
                         "itemId": 280, "itemIdSize": 4, "count": 284, "countSize": 4,
                         "trigger": 288, "triggerSize": 4},
    }


def mark_executed(result: dict, exit_code: int) -> dict:
    """wrapper 调用开始的记账：**executed 一旦为真，退出码非 0 也不得降级**。"""
    if result.get("executed") and not result.get("called"):
        raise AttachSpecError("executed_cannot_be_downgraded",
                              "executed=true 的卡片不允许被改回 called=false")
    result["executed"] = True
    result["called"] = True
    result["exitCode"] = int(exit_code)
    result["outcomeUncertain"] = bool(exit_code != 0)
    return result


def build_card(*, hosts: Sequence[int], item_id: int, count: int = 1, trigger: int = 0,
               baseline: bytes | None = None, session: dict | None = None,
               compiled_artifacts: dict | None = None, level_id: int = 1073741843,
               scope: str = TRANSPORT_SCOPE, nonce: int | None = None,
               ttl_ms: int = 600000, baseline_run: str | None = None,
               baseline_run_dir: str | None = None, message_id: int | None = None,
               target_config: dict | None = None) -> dict:
    """组一张 transport 卡片（**内存产物**；落盘由 :func:`write_card` 用 caller 给的目录做）。

    baseline 双分支（口径 3，两分支都在这里走同一条链）：
    * 有真实 baseline（``baseline`` + ``session`` + ``decode_run`` 独立验收通过）⇒ ``launchable=true``；
    * 否则 ⇒ ``launchable=false`` + ``REAL_BASELINE_REQUIRES_RUNNING_TARGET``。
    """
    spec = normalized_spec(level_id=level_id, hosts=hosts, configuration={"expected": {
        "kind": KIND_DROP_STUFF, "entityId": int(list(hosts)[0]), "itemId": int(item_id),
        "count": int(count), "trigger": int(trigger)}})
    spec_bytes = json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8")
    layout_bytes = json.dumps(layout_from_probe(), ensure_ascii=False, indent=2).encode("utf-8")
    resolved_nonce = int(nonce) if nonce else (int.from_bytes(os.urandom(8), "big") | 1)
    if resolved_nonce == 0:
        raise AttachSpecError("NONCE_ZERO_REFUSED", "nonce 必须非 0")
    deadline = int((_uptime_ms() or 0) + int(ttl_ms))       # **只算一次**：宏与卡片同值
    session = dict(session or {})
    for field in ("pid", "tid", "processCreation", "threadCreation", "image"):
        if field not in session:
            raise AttachSpecError("SESSION_FIELD_MISSING", f"session.{field}（真实 session 必填）")
    expires_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl_ms / 1000.0))
    resolved_message_id = int(message_id if message_id is not None
                              else ((target_config or {}).get("messageId") or 0))
    macros = (_TARGET_CONFIG_H
              .replace("@@ACTION@@", str(ACTION_CODE))
              .replace("@@PROTOCOL@@", str(RECEIPT_VERSION))
              .replace("@@KIND@@", str(_ACTIVE_KIND)).replace("@@KINDSTRING@@", kind_string_for(_ACTIVE_KIND))
              .replace("@@ATTACHRVA@@", ATTACH_ABI["rva"])
              .replace("@@NONCE@@", str(resolved_nonce))
              .replace("@@DEADLINE@@", str(deadline))
              .replace("@@PID@@", str(int(session["pid"])))
              .replace("@@TID@@", str(int(session["tid"])))
              .replace("@@CREATION@@", str(int(session["processCreation"])))
              .replace("@@THREADCREATION@@", str(int(session["threadCreation"])))
              .replace("@@IMAGE@@", str(session["image"]))
              # messageId：优先用调用方传入的**真实注册值**（--from-run 从 run.json 带入），
              # 否则退回 target_config 的注册值，再否则 0（未注册 ⇒ 卡片不声称可派发）
              .replace("@@MESSAGEID@@", str(resolved_message_id))
              .replace("@@LEVELANCHOR@@", _anchor_literal("LEVEL"))
              .replace("@@PLACEANCHOR@@", _anchor_literal("PLACE"))
              .replace("@@SAVEANCHOR@@", _anchor_literal("SAVE"))
              .replace("@@ENTITYIDS@@", str((target_config or {}).get("entityIds") or 0))
              .replace("@@RUN@@", str(Path(__file__).resolve().parent).replace("\\", "\\\\")))
    baseline_bytes = bytes(baseline) if baseline is not None else b""
    has_real_baseline = bool(baseline_bytes) and bool(session) and bool(
        decode_run_verdict(baseline_run_dir)["ok"])
    refusals = [] if has_real_baseline else [{"code": "REAL_BASELINE_REQUIRES_RUNNING_TARGET",
                                              "detail": "YuanShen.exe 未运行或 baseline 未过 "
                                                        "decode_run 独立验收"}]
    route = _transport_route()                       # 逐键对齐 dispatch.py:158-161
    if int(route["action"]) != ACTION_CODE or int(route["protocol"]) != RECEIPT_VERSION:
        raise AttachSpecError("TRANSPORT_ROUTE_MISMATCH",
                              f"route action/protocol={route['action']}/{route['protocol']} != "
                              f"{ACTION_CODE}/{RECEIPT_VERSION}")
    scope = str(route["scope"])
    sources = {"drop_stuff_attach.py": str(Path(__file__).resolve()),
               ACCEPTOR_RELATIVE: str(REPO_ROOT / ACCEPTOR_RELATIVE),
               "component_attachment.h": str(SHARED_NATIVE / "component_attachment.h"),
               "component_attachment.cpp": str(SHARED_NATIVE / "component_attachment.cpp")}
    # 键 = 相对路径（dispatch.py:171-173：验收器必须按相对路径钉住，否则 COMPONENT_ACCEPTOR_NOT_PINNED）
    source_hashes = {}
    for key, path in sources.items():
        candidate = Path(path)
        if candidate.is_file():
            source_hashes[key if "/" in key else candidate.name] = _sha256_file(candidate)
    files: dict[str, bytes] = {"target_config.h": macros.encode("utf-8"),
                               "normalized-spec.json": spec_bytes,
                               "receipt-layout.json": layout_bytes,
                               "baseline-snapshot.bin": baseline_bytes}
    files.update({name: bytes(payload) for name, payload in (compiled_artifacts or {}).items()})
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(files.items())}
    wrapper_name = str(route["wrapper"])
    wrapper_text = ("# 固定 wrapper（由 drop_stuff_attach.py 生成）：卡片 pin 校验后才派发\n"
                    f"$Action = {ACTION_CODE}\n$Protocol = {RECEIPT_VERSION}\n"
                    f"$Nonce = {int(nonce or 0)}\n$Scope = '{scope}'\n")
    files[wrapper_name] = wrapper_text.encode("utf-8")
    hashes[wrapper_name] = hashlib.sha256(files[wrapper_name]).hexdigest()
    keys = required_hash_keys(route)
    compiled = bool(compiled_artifacts) and all(
        name in files for name in keys if name != "prepared.json")
    ok = bool(compiled and has_real_baseline)
    prepared = {
        "schemaVersion": 1, "kind": TRANSPORT_PREPARED_KIND, "run": None, "levelId": int(level_id),
        "actionCode": ACTION_CODE, "receiptVersion": RECEIPT_VERSION, "scope": scope,
        "launchable": has_real_baseline, "compileOnly": False, "reviewed": True, "allowWrites": True,
        "session": session, "nonce": resolved_nonce,
        "deadline": deadline, "expiresUtc": expires_utc,
        # messageId 三处相等契约的第 2 处（另两处 = target_config.h / build-result.json）
        "messageId": int(message_id or 0),
        "baselineRun": baseline_run, "baselineSha256": hashes.get("baseline-snapshot.bin") or None,
        "normalizedSpecSha256": hashes["normalized-spec.json"], "sourceHashes": source_hashes,
        "wrapperName": wrapper_name, "hashes": hashes, "refusals": refusals,
        "executed": False, "called": False,
    }
    prepared_bytes = json.dumps(prepared, ensure_ascii=False, indent=2).encode("utf-8")
    files["prepared.json"] = prepared_bytes
    hashes["prepared.json"] = hashlib.sha256(prepared_bytes).hexdigest()
    build_result = {
        "schemaVersion": 1, "kind": TRANSPORT_BUILD_KIND, "ok": ok, "compiled": compiled,
        "launchable": has_real_baseline, "compileOnly": False, "run": None,
        "actionCode": ACTION_CODE, "receiptVersion": RECEIPT_VERSION, "scope": scope,
        "wrapperName": wrapper_name, "hashes": hashes, "sourceHashes": source_hashes,
        "called": False, "executed": False, "nativeStarted": False, "outcomeUncertain": False,
        # ③ 镜像 prepared 的原生绑定（session/nonce/deadline/baseline）——两件接口件字段一致
        "session": session, "nonce": resolved_nonce, "deadline": deadline,
        "expiresUtc": expires_utc, "baselineRun": baseline_run,
        # messageId 三处相等契约的第 3 处（另两处 = target_config.h / prepared.json）
        "messageId": int(message_id or 0),
        "baselineSha256": hashes.get("baseline-snapshot.bin") or None,
        "normalizedSpecSha256": hashes["normalized-spec.json"],
        "refusals": refusals, "preparedSha256": hashes["prepared.json"],
        "executedSemantics": "wrapper 调用一开始 executed=true；exit!=0 也不得降级（mark_executed）",
    }
    missing = [name for name in keys if name not in hashes]
    if missing:
        build_result["ok"] = False
        build_result["refusals"].append({"code": "HASHES_INCOMPLETE", "detail": ",".join(missing)})
    return {"ok": bool(build_result["ok"]), "branch": ("launchable" if has_real_baseline
                                                       else "REAL_BASELINE_REQUIRES_RUNNING_TARGET"),
            "files": files, "hashes": hashes, "sourceHashes": source_hashes,
            "buildResult": build_result, "prepared": prepared, "spec": spec,
            "missingHashKeys": missing, "gameDispatch": False}


def write_card(card: dict, out_dir) -> dict:
    """把卡片落盘到**caller 给的目录**（不写死 .runtime；shell 写禁时由 root 阶段调用）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, payload in card["files"].items():
        (out / name).write_bytes(payload)
        written[name] = len(payload)
    (out / "build-result.json").write_bytes(
        json.dumps(card["buildResult"], ensure_ascii=False, indent=2).encode("utf-8"))
    written["build-result.json"] = (out / "build-result.json").stat().st_size
    return {"ok": True, "dir": str(out.resolve()), "written": written}


def card_main(argv: list[str]) -> int:
    out = None
    hosts: list[int] = []
    item = 0
    from_run = None
    session: dict = {}
    for index, token in enumerate(argv):
        if token == "--out" and index + 1 < len(argv):
            out = Path(argv[index + 1])
        if token == "--host" and index + 1 < len(argv):
            hosts.append(int(argv[index + 1]))
        if token == "--item" and index + 1 < len(argv):
            item = int(argv[index + 1])
        if token == "--from-run" and index + 1 < len(argv):
            from_run = Path(argv[index + 1])
        # session 五元组（真实 session 才能走 launchable；fixture 只会落到 false + 具名码）
        if token == "--session-pid" and index + 1 < len(argv):
            session["pid"] = int(argv[index + 1])
        if token == "--session-tid" and index + 1 < len(argv):
            session["tid"] = int(argv[index + 1])
        if token == "--session-creation" and index + 1 < len(argv):
            session["processCreation"] = int(argv[index + 1])
        if token == "--session-thread" and index + 1 < len(argv):
            session["threadCreation"] = int(argv[index + 1])
        if token == "--session-image" and index + 1 < len(argv):
            session["image"] = argv[index + 1]
    try:
        if not item:
            print(json.dumps({"ok": False, "code": "ITEM_ID_REQUIRED_INPUT",
                              "detail": "--item <道具配置ID> 必填（业务字段不许写死）"},
                             ensure_ascii=False))
            return 2
        # 从已构建的候选目录读入**真实产物**（八项 hashes 里的两件编译产物由此落到卡上）
        artifacts: dict = {}
        run_message_id = None
        if from_run is not None:
            meta_path = Path(from_run) / "run.json"
            if meta_path.is_file():
                run_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                run_message_id = int(run_meta.get("messageId") or 0) or None
            for rel, key in (("include/dropstuff_target_config.h", "target_config.h"),
                             ("build/hook_receipt.dll", "hook_receipt.dll"),
                             ("build/hook_receipt_probe.exe", "hook_receipt_probe.exe")):
                path = Path(from_run) / rel
                if path.is_file():
                    artifacts[key] = path.read_bytes()
        card = build_card(hosts=hosts or [1077936132], item_id=item,
                          session=(session or None), message_id=run_message_id,
                          compiled_artifacts=(artifacts or None))
    except AttachSpecError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False))
        return 1
    report = {"ok": card["ok"], "branch": card["branch"],
              "missingHashKeys": card["missingHashKeys"],
              "buildResult": card["buildResult"], "prepared": card["prepared"]}
    if out is not None and argv[0] == "--write-card":
        report["write"] = write_card(card, out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if card["ok"] else 1


_MAIN_V8 = _main


def _main(argv: list[str]) -> int:  # noqa: F811 —— revision 9：追加 --card / --write-card
    global _ACTIVE_KIND
    # **`--kind` 必须在这里解析**（本定义生效；:1891 同名 `_main` 被它遮蔽）；
    # 解析后**从 argv 剥离**再委派，避免下游把 `--kind` 当未知参数。
    stripped: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--kind" and index + 1 < len(argv):
            try:
                _ACTIVE_KIND = require_executable_kind(int(argv[index + 1]))
            except Exception as error:  # noqa: BLE001 - 具名拒绝，不打 traceback
                code = getattr(error, "code", "KIND_PARSE_ERROR")
                print(json.dumps({"ok": False, "code": code,
                                  "detail": str(getattr(error, "detail", error))[:200]},
                                 ensure_ascii=False))
                return 1
            index += 2
            continue
        if token.startswith("--kind="):
            try:
                _ACTIVE_KIND = require_executable_kind(int(token.split("=", 1)[1]))
            except Exception as error:  # noqa: BLE001
                code = getattr(error, "code", "KIND_PARSE_ERROR")
                print(json.dumps({"ok": False, "code": code,
                                  "detail": str(getattr(error, "detail", error))[:200]},
                                 ensure_ascii=False))
                return 1
            index += 1
            continue
        stripped.append(token)
        index += 1
    if stripped and stripped[0] in ("--card", "--write-card"):
        return card_main(stripped)
    return _MAIN_V8(stripped)


if __name__ == "__main__":  # pragma: no cover
    _ensure_utf8_io()
    raise SystemExit(_main(sys.argv[1:]))

