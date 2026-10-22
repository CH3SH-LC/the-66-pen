"""场景快照 ABI 适配（v1 512 实体/33208 B，v2 4096 实体/262584 B）。

## 为什么在这里加这个文件

模板授权链的 accept 族（``accept_item.py:23`` / ``accept_currency.py:23`` / …）把
``SNAPSHOT_BYTES = 33208`` **写死**，那是 v1。蒙德目标关卡有 **1613 个实体**（>512），
必须走 v2 = 262584 B。**本文件是原入口的共享适配器**：保留 v1 为默认、在原入口新增 v2。

## ABI 事实（逐条带出处，全部是仓内已实现的方案）

* v1 = 512 实体 / 33208 B：``tools/game-executor/asset_inspection_receipt.py:28``（``ASSET_SNAPSHOT_ABI``）
* v2 = 4096 实体 / 262584 B：``tools/game-executor/asset_inspection_build.py:61``（``GS_LARGE_SCENE``）、
  ``tools/game-executor/decode_context_snapshot.py:73``
* 尺寸即版本（两个尺寸不重叠）；头部前 8 字节 = LE ``<II (len(raw), version)``。
* **不改共享 ``game_context_snapshot`` 的 ABI 默认**（用户明确要求）：本文件只是**接受两种尺寸**，
  默认值仍是 v1 的 33208。

## 单一真源（本文件不另立第二份注册表）

尺寸 → 版本、版本 → 实体容量、版本 → ``GS_LARGE_SCENE`` 三者**从**
``tools/game-executor/decode_context_snapshot.py`` 的 ``SNAPSHOT_LAYOUTS`` /
``SNAPSHOT_LARGE_SCENE`` **推导**（那是本仓唯一的快照布局注册表，NPC 侧 kind17 双 ABI 修复
``docs/mondstadt/npc_travel/impl/KIND17-DUAL-ABI.md`` 用的是同一份）。导入时自检：推导值必须等于
冻结的 v1/v2 实数（33208→1/512、262584→2/4096），否则 ``snapshot_abi_registry_drift`` 具名报错。
解码器不可导入时（例如本文件被单独 doctest）退回冻结别名，值相同。

## 收据布局（accept 族不再写死偏移）

原生收据（``item_native_adapter.h`` / ``currency_native_adapter.h``）是**自述长度**的定长结构：

    NativeItemReceipt / NativeCurrencyReceipt =
        {size, version, sehCode, afterSceneUnchanged}   # RECEIPT_HEADER_BYTES = 16
        + action                                        # ItemActionResult 104 / CurrencyActionResult 64
        + expected[snapshotBytes]                       # 审阅基线快照
        + after[snapshotBytes]                          # 动作后快照
        + workspace{ capture, beforeCatalog, afterCatalog }

⇒ :func:`receipt_layout` 按快照尺寸推出全部偏移与收据总长（v1 时逐值等于历史常量：
item 120/33328/369784/632088/894392、currency 80/33288/369744/632048/894352），
:func:`snapshot_size_for_receipt` 反向从收据长度解出快照尺寸。两者是**互相独立的观测**，
accept 族要求它们一致才继续（不许拿一个值自证自己）。

## 语义

:func:`validate_snapshot_size` 接受 ``33208`` / ``262584``，其它值**具名拒绝**；
:func:`version_for_size` 给出尺寸对应的版本号；:func:`size_for_entity_count` 按实体数选尺寸；
:func:`large_scene_for_size` 给出该尺寸该用的 ``GS_LARGE_SCENE``（0/1，编译期开关）。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

_EXECUTOR = Path(__file__).resolve().parents[1]
if str(_EXECUTOR) not in sys.path:            # 单一真源（解码器）在 tools/game-executor 下
    sys.path.insert(0, str(_EXECUTOR))

__all__ = [
    "SIZES",
    "DEFAULT_BYTES",
    "DEFAULT_VERSION",
    "CAPACITY",
    "LARGE_SCENE",
    "RECEIPT_HEADER_BYTES",
    "SnapshotAbiError",
    "version_for_size",
    "validate_snapshot_size",
    "size_for_entity_count",
    "entity_capacity_for_size",
    "large_scene_for_size",
    "validate_snapshot_payload",
    "receipt_layout",
    "snapshot_size_for_receipt",
]


class SnapshotAbiError(RuntimeError, ValueError):
    """具名拒绝（带 ``code``，便于链上按码处理）。

    同时是 ``ValueError``：链上的错误处理统一是
    ``except (OSError, ValueError, KeyError, TypeError, struct.error)``
    （``accept_currency.accept_run`` / 各 ``main``），而解码器的同类拒绝
    （``decode_context_snapshot.SnapshotAbiError``）也是 ``ValueError``。
    两种捕获风格都能接住它，拒绝码不会因为没被接住而变成崩溃栈。
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---- 冻结别名（导入时与推导值互校；两个受审 ABI 的实数） --------------------- #
_FROZEN_SIZE_TO_VERSION: dict[int, int] = {33208: 1, 262584: 2}
_FROZEN_CAPACITY: dict[int, int] = {1: 512, 2: 4096}
_FROZEN_LARGE_SCENE: dict[int, int] = {1: 0, 2: 1}

try:                                          # 唯一注册表在解码器里
    import decode_context_snapshot as _decoder_abi
except ImportError:                           # pragma: no cover - 单独导入本文件时
    _decoder_abi = None


def _derive_registry() -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    """从解码器的注册表推导 (尺寸→版本, 版本→容量, 版本→GS_LARGE_SCENE)。"""
    if _decoder_abi is None:                  # pragma: no cover - 退回冻结别名
        return dict(_FROZEN_SIZE_TO_VERSION), dict(_FROZEN_CAPACITY), dict(_FROZEN_LARGE_SCENE)
    layouts = getattr(_decoder_abi, "SNAPSHOT_LAYOUTS", None)
    if not layouts:
        raise SnapshotAbiError(
            "snapshot_abi_registry_missing",
            "decode_context_snapshot.SNAPSHOT_LAYOUTS 不可用，无法推导受审 ABI 注册表",
        )
    size_to_version = {int(size): int(version) for version, size in layouts}
    capacity = {int(version): int(counts[0]) for (version, _size), counts in layouts.items()}
    large_scene = {int(version): int(flag)
                   for version, flag in getattr(_decoder_abi, "SNAPSHOT_LARGE_SCENE", {}).items()}
    return size_to_version, capacity, large_scene


_SIZE_TO_VERSION, CAPACITY, LARGE_SCENE = _derive_registry()
if _SIZE_TO_VERSION != _FROZEN_SIZE_TO_VERSION or CAPACITY != _FROZEN_CAPACITY or \
        LARGE_SCENE != _FROZEN_LARGE_SCENE:
    raise SnapshotAbiError(                    # 推导与实测不符 ⇒ 不静默
        "snapshot_abi_registry_drift",
        f"推导 {_SIZE_TO_VERSION}/{CAPACITY}/{LARGE_SCENE} != 冻结 "
        f"{_FROZEN_SIZE_TO_VERSION}/{_FROZEN_CAPACITY}/{_FROZEN_LARGE_SCENE}",
    )

#: 已知 ABI 尺寸（= 版本）。顺序即版本顺序。
SIZES: tuple[int, ...] = tuple(size for size, _version in sorted(_SIZE_TO_VERSION.items(), key=lambda kv: kv[1]))
DEFAULT_BYTES: int = SIZES[0]      # v1，保持既有行为不变
DEFAULT_VERSION: int = _SIZE_TO_VERSION[DEFAULT_BYTES]

#: 原生收据的固定头：``{size, version, sehCode, afterSceneUnchanged}`` 四个 uint32。
RECEIPT_HEADER_BYTES: int = 16


def version_for_size(size: int) -> int:
    if size not in _SIZE_TO_VERSION:
        raise SnapshotAbiError(
            "unknown_snapshot_size",
            f"{size} 不在已知 ABI 尺寸 {SIZES}（v1=512 实体, v2=4096 实体）",
        )
    return _SIZE_TO_VERSION[size]


def validate_snapshot_size(value, code: str = "SNAPSHOT_ABI") -> int:
    """把 ``value`` 校验成已知 ABI 尺寸并返回；不认识就按 ``code`` 具名拒绝。

    刻意**不做类型强转**：``True``/``"33208"`` 之类一律拒绝，避免把布尔当尺寸。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotAbiError(code, f"snapshotBytes 必须是 int，收到 {value!r}")
    if value not in _SIZE_TO_VERSION:
        raise SnapshotAbiError(code, f"snapshotBytes={value} 不在已知 ABI 尺寸 {SIZES}")
    return value


def size_for_entity_count(entity_count: int) -> int:
    """按实体数选 ABI 尺寸：>512 实体 ⇒ v2（蒙德 1613 实体的情形）。"""
    if isinstance(entity_count, bool) or not isinstance(entity_count, int) or entity_count < 0:
        raise SnapshotAbiError("bad_entity_count", f"{entity_count!r}")
    for version in sorted(CAPACITY):
        if entity_count <= CAPACITY[version]:
            return SIZES[version - 1]
    raise SnapshotAbiError("no_abi_fits", f"{entity_count} 实体超过 v2 上限 {CAPACITY[2]}")


def entity_capacity_for_size(size: int) -> int:
    """该尺寸的实体上限（v1 512 / v2 4096）。"""
    return CAPACITY[version_for_size(validate_snapshot_size(size))]


def large_scene_for_size(size: int) -> int:
    """该尺寸编译期该用的 ``GS_LARGE_SCENE``（v1 0、v2 1）。

    逐 run 隔离的 C++ 副本据此开关 ABI（``native/game_context_snapshot.h:75-92``），
    **不改共享头文件的默认值**（默认仍是 0 = v1）。
    """
    return LARGE_SCENE[version_for_size(validate_snapshot_size(size))]


def validate_snapshot_payload(raw, code: str = "SNAPSHOT_ABI") -> dict:
    """按 payload **自述**校验一个快照：字节数必须是受审 ABI，头部 structSize/version 必须自洽。

    返回 ``{'bytes', 'version', 'maxEntities', 'largeScene'}``；任何不一致都按 ``code`` 具名拒绝。
    全零头（未初始化载荷：编译期占位/离线合成）按字节数接受，版本按尺寸取。
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise SnapshotAbiError(code, f"快照载荷必须是 bytes，收到 {type(raw).__name__}")
    data = bytes(raw)
    size = validate_snapshot_size(len(data), code)
    expected = _SIZE_TO_VERSION[size]
    if _decoder_abi is not None:
        try:
            derived = _decoder_abi.derive_snapshot_abi(data, code)
        except Exception as error:             # decode_context_snapshot.SnapshotAbiError
            raise SnapshotAbiError(getattr(error, "code", code), getattr(error, "detail", str(error))) from None
        version = int(derived.get("version") or expected)
        if version != expected:
            raise SnapshotAbiError(code, f"载荷自述 version={version}，与 {size} 对应的 v{expected} 不符")
        return {"bytes": size, "version": version, "maxEntities": int(derived.get("maxEntities") or
                CAPACITY[expected]), "largeScene": LARGE_SCENE[expected]}
    if len(data) < RECEIPT_HEADER_BYTES:       # pragma: no cover - 极端短载荷
        raise SnapshotAbiError(code, f"快照载荷只有 {len(data)} 字节")
    struct_size, version, _status, _flags = struct.unpack_from("<4I", data, 0)
    if struct_size not in (0, size):
        raise SnapshotAbiError("snapshot_size_mismatch", f"头部 structSize={struct_size} != {size} 字节")
    if version not in (0, expected):
        raise SnapshotAbiError(code, f"头部 version={version} 与 {size} 对应的 v{expected} 不符")
    return {"bytes": size, "version": version or expected, "maxEntities": CAPACITY[expected],
            "largeScene": LARGE_SCENE[expected]}


def _positive_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SnapshotAbiError("receipt_layout_argument", f"{name}={value!r} 必须是正整数")
    return value


def receipt_layout(snapshot_size: int, *, action_bytes: int, catalog_bytes: int,
                   capture_bytes: int) -> dict:
    """按快照尺寸推出原生收据的全部偏移与总长（v1 时等于历史写死的常量）。

    ``action_bytes`` = ``ItemActionResult`` 104 / ``CurrencyActionResult`` 64；
    ``catalog_bytes`` = ``receipt.py`` 的 ``CATALOG_BYTES``（262304）；
    ``capture_bytes`` = ``sizeof(TemplateCatalogCaptureWorkspace)``（303248，见调用方的推导式）。
    """
    size = validate_snapshot_size(snapshot_size, "receipt_layout")
    action_bytes = _positive_int(action_bytes, "action_bytes")
    catalog_bytes = _positive_int(catalog_bytes, "catalog_bytes")
    capture_bytes = _positive_int(capture_bytes, "capture_bytes")
    action_offset = RECEIPT_HEADER_BYTES
    expected_offset = action_offset + action_bytes
    after_offset = expected_offset + size
    before_catalog_offset = after_offset + size + capture_bytes
    after_catalog_offset = before_catalog_offset + catalog_bytes
    receipt_bytes = after_catalog_offset + catalog_bytes
    return {
        "snapshotBytes": size,
        "version": version_for_size(size),
        "largeScene": large_scene_for_size(size),
        "receiptBytes": receipt_bytes,
        "actionOffset": action_offset,
        "expectedSnapshotOffset": expected_offset,
        "afterSnapshotOffset": after_offset,
        "beforeCatalogOffset": before_catalog_offset,
        "afterCatalogOffset": after_catalog_offset,
        "catalogBytes": catalog_bytes,
        "captureBytes": capture_bytes,
        "fixedBytes": receipt_bytes - 2 * size,
    }


def snapshot_size_for_receipt(receipt_bytes: int, *, action_bytes: int, catalog_bytes: int,
                              capture_bytes: int, code: str = "receipt_size") -> int:
    """从收据长度**反向**解出快照尺寸（与声明字段互相独立的一次观测）。

    长度必须恰好等于 ``需求头 + action + 2*快照 + capture + 2*catalog``；解出非受审尺寸即具名拒绝。
    """
    if isinstance(receipt_bytes, bool) or not isinstance(receipt_bytes, int) or receipt_bytes <= 0:
        raise SnapshotAbiError(code, f"receiptBytes={receipt_bytes!r} 必须是正整数")
    action_bytes = _positive_int(action_bytes, "action_bytes")
    catalog_bytes = _positive_int(catalog_bytes, "catalog_bytes")
    capture_bytes = _positive_int(capture_bytes, "capture_bytes")
    fixed = RECEIPT_HEADER_BYTES + action_bytes + capture_bytes + 2 * catalog_bytes
    remainder = receipt_bytes - fixed
    if remainder <= 0 or remainder % 2:
        raise SnapshotAbiError(code, f"{receipt_bytes} 减去固定段 {fixed} 不是两个受审快照尺寸")
    size = remainder // 2
    try:
        version_for_size(size)
    except SnapshotAbiError as error:
        raise SnapshotAbiError(code, f"{receipt_bytes} ⇒ 快照 {size}：{error.detail}") from None
    return size
