#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""combat-encounters: **独立读回** —— 从实体读回，而不是只信回执。

=============================================================================
0. 为什么这个文件必须独立（本文件最重要的一条）
=============================================================================
``component_mounter.py`` 写出的 ``manifest.json`` 是一份**声明**。如果读回只是
「再读一遍那份声明」，那它证明的只有「写入器认为自己成功了」——
本工程把这种情况记作**同源自比**（``SYNC_PROOF_SAME_SOURCE_NOT_ACCEPTED``，
见 ``tools/mondstadt/life/dropstuff/ABI-DROPSTUFF.md`` §9）。

因此本文件的硬约束是：

* **不 import ``component_mounter``**（自检会实测这一条，不是口头声明）；
* 输入是 ``MWCAP`` **原始内存转储** —— 那是写入器**真正读过的字节**；
* 本文件按**自己冻结的**布局常量（``FROZEN_LAYOUTS``）**重走一遍**结构：
  实体根 → SET 哈希集合 → LIST 数组 → 每个组件行 → 每行 config，逐字段读，
  并核对回指（wrapper→owner、config→wrapper、config→owner）；
* 然后把**自己从字节里读出来的东西**与 manifest 的声明**逐条比对**；
  声明错了 ⇒ 读回**失败**（``declaration_mismatch``），而不是跟着声明走。

⇒ 这是**内容级的独立读回**：两套实现、两个入口、只共享一份磁盘字节。

=============================================================================
1. 诚实边界（不许当成「游戏里验证过了」）
=============================================================================
**本文件证明的**：给定一份 MWCAP 字节，组件行的**存在性、kind、数量和前缀不变性**
可以**不依赖写入器代码**被重推出来；写入器的声明与重推结果一致时才算通过。

**本文件不证明的**：
  * **这些字节来自游戏进程** —— 那取决于产生转储的那次注入。
    本机可复现的转储来自**进程内桩内存**（见 mounter 的 ``--driver``）；
    ``source.provenance`` 字段会如实标出是 ``STUB_IN_PROCESS`` 还是 ``GAME_PROCESS``；
  * 引擎**是否加载**了我们合成的组件；
  * 性能、外观、拾取行为等任何玩法结论。

读回**不碰游戏**：它只读文件。真正从游戏实体读回，需要 leader 在独占原生窗口
里用同一套布局取转储（world-contract v26 ``executionBoundaries.nativeWrites``）。

=============================================================================
2. 用法（可被 runner 调用）
=============================================================================
    python -B tools/mondstadt/combat/native/readback.py verify \\
        --capture <dir>/capture.mwcap --manifest <dir>/manifest.json

    python -B tools/mondstadt/combat/native/readback.py selftest

退出码：``0`` = 读回通过且声明一致；``1`` = 读回失败／声明不符（具名原因）；
``2`` = 输入损坏（格式/版本/布局不匹配，fail-closed）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Sequence

MODULE = "combat-encounters"
TOOL = "component-readback"
TOOL_VERSION = 1
CONTRACT_VERSION = 26
CAPTURE_FORMAT = "MWCAP"
CAPTURE_MAGIC = b"MWCAP001"

#: 头部字段偏移。**全部显式写出，不用 struct 的隐式对齐** ——
#: ``struct.calcsize("<IIQI") == 20``（``Q`` 要求 8 字节对齐，会插 4 字节填充），
#: 与 C++ 里手写的 ``memcpy(out + k, &v, sizeof v)`` 不一致。这个坑在本文件
#: 第一版里真的踩了：头部按 24 字节算，而写入器写的是 28 字节，于是读回把
#: 记录的 8 字节地址当成了版本号。两头都用显式偏移，才不会再错。
CAPTURE_OFFSET_VERSION = 8
CAPTURE_OFFSET_RECORDS = 12
CAPTURE_OFFSET_OWNER = 16
CAPTURE_OFFSET_LAYOUT = 24
CAPTURE_HEADER_BYTES = 28
CAPTURE_RECORD_HEADER_BYTES = 12
CAPTURE_LAYOUT_ID = "component-attachment-native-v1"
MANIFEST_FORMAT = "MWMANIFEST"
MANIFEST_VERSION = 1

#: **本文件自己冻结的**布局。它**不**从写入器导入。
#: 关键：写入器若换了布局，必须同时升 ``CAPTURE_VERSION``；旧版本在这里没有
#: 常量 ⇒ 具名拒绝（``capture_version_unsupported``）。这就是 fail-closed 的着力点。
FROZEN_LAYOUTS: dict[int, dict[str, int | str]] = {
    1: {
        "layoutId": CAPTURE_LAYOUT_ID,
        "ownerClassOffset": 0x00,
        "ownerSetOffset": 0x30,
        "ownerListOffset": 0x68,
        "ownerStateOffset": 0x9C,
        "arrayLengthOffset": 0x18,
        "arrayElementOffset": 0x20,
        "listHeaderBytes": 0x20,
        "setHeaderBytes": 0x38,
        "setBucketsOffset": 0x10,
        "setSlotsOffset": 0x20,
        "setCountOffset": 0x28,
        "setLastIndexOffset": 0x2C,
        "setFreeHeadOffset": 0x30,
        "wrapperBytes": 0x38,
        "wrapperBackrefOffset": 0x20,
        "wrapperConfigOffset": 0x28,
        "wrapperEnabledOffset": 0x30,
        "wrapperKindOffset": 0x34,
        "configBackrefOffset": 0x18,
        "configOwnerOffset": 0x20,
        "slotBytes": 12,
        "maxComponents": 256,
        "addressLow": 0x10000,
        "addressHigh": 0x0000800000000000,
    }
}


class ReadbackError(RuntimeError):
    """具名拒绝。每条都带 ``code``。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        return {"ok": False, "code": self.code, "detail": self.detail}


# ---------------------------------------------------------------------------
# MWCAP 解析
# ---------------------------------------------------------------------------
class CapturedMemory:
    """从 MWCAP 字节重建「一块只读内存」，**只含转储真的覆盖到的字节**。

    关键性质：任何越界读都返回 ``None``，绝不补零、绝不猜。
    因此「读回成功」蕴含「这些字节确实在转储里」，不是靠默认值凑出来的。
    """

    def __init__(self, regions: list[tuple[int, bytes]], header: dict) -> None:
        self._regions = sorted(regions, key=lambda item: item[0])
        self.header = header

    def read(self, address: int, size: int) -> bytes | None:
        if size <= 0:
            return None
        for base, blob in self._regions:
            if base <= address and address + size <= base + len(blob):
                start = address - base
                return blob[start:start + size]
        return None

    def uint64(self, address: int) -> int | None:
        raw = self.read(address, 8)
        return None if raw is None else struct.unpack_from("<Q", raw)[0]

    def int32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return None if raw is None else struct.unpack_from("<i", raw)[0]

    def uint32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return None if raw is None else struct.unpack_from("<I", raw)[0]

    def uint8(self, address: int) -> int | None:
        raw = self.read(address, 1)
        return None if raw is None else raw[0]

    @property
    def coveredBytes(self) -> int:
        return sum(len(blob) for _base, blob in self._regions)

    @property
    def regionCount(self) -> int:
        return len(self._regions)


def parse_capture_bytes(data: bytes, label: str = "<bytes>") -> tuple[CapturedMemory, dict]:
    """解析 MWCAP 字节。**不信任任何长度字段**：逐条边界核对，越界即拒绝。

    与 ``parse_capture`` 分开，是为了让「解析器对损坏输入会不会拒绝」这件事可以
    在**内存里**被验证 —— 不需要临时目录、不落任何文件。
    """
    if len(data) < CAPTURE_HEADER_BYTES:
        raise ReadbackError("capture_truncated", f"{label} 只有 {len(data)} 字节")
    if data[:8] != CAPTURE_MAGIC:
        raise ReadbackError(
            "capture_bad_magic",
            f"前 8 字节是 {data[:8]!r}，不是 {CAPTURE_MAGIC!r}",
        )
    version = struct.unpack_from("<I", data, CAPTURE_OFFSET_VERSION)[0]
    records = struct.unpack_from("<I", data, CAPTURE_OFFSET_RECORDS)[0]
    owner = struct.unpack_from("<Q", data, CAPTURE_OFFSET_OWNER)[0]
    layout = struct.unpack_from("<I", data, CAPTURE_OFFSET_LAYOUT)[0]
    if version not in FROZEN_LAYOUTS:
        raise ReadbackError(
            "capture_version_unsupported",
            f"转储声明 captureVersion={version}，而本文件只冻结了 "
            f"{sorted(FROZEN_LAYOUTS)} 的布局；**不允许**用旧常量猜新格式",
        )
    if layout != 1:
        raise ReadbackError(
            "capture_layout_unknown",
            f"转储声明 layoutId 序号={layout}，本文件认识的是 1（{CAPTURE_LAYOUT_ID}）",
        )
    regions: list[tuple[int, bytes]] = []
    seen: dict[int, int] = {}
    cursor = CAPTURE_HEADER_BYTES
    for index in range(records):
        if cursor + 12 > len(data):
            raise ReadbackError(
                "capture_record_truncated",
                f"第 {index} 条记录的 12 字节头越界（cursor={cursor} len={len(data)}）",
            )
        address, length = struct.unpack_from("<QI", data, cursor)
        cursor += 12
        if cursor + length > len(data):
            raise ReadbackError(
                "capture_record_truncated",
                f"第 {index} 条记录体越界：address=0x{address:x} length={length} "
                f"cursor={cursor} len={len(data)}",
            )
        blob = data[cursor:cursor + length]
        cursor += length
        # 同一地址可能被读多次（写入器确实会重复读）。只保留**首次**，
        # 但必须逐字节一致 —— 不一致说明捕获期内存变过，读回必须拒绝。
        if address in seen:
            first = regions[seen[address]][1]
            if first != blob:
                raise ReadbackError(
                    "capture_region_unstable",
                    f"0x{address:x} 被读了多次但内容不一致（len {len(first)} vs {len(blob)}）"
                    "；捕获期内存不稳定，读回结论不可用",
                )
            continue
        seen[address] = len(regions)
        regions.append((address, blob))
    if cursor != len(data):
        raise ReadbackError(
            "capture_trailing_bytes",
            f"解析完 {records} 条记录后还剩 {len(data) - cursor} 字节未被解释",
        )
    header = {
        "version": version,
        "records": records,
        "distinctRegions": len(regions),
        "owner": owner,
        "layoutId": CAPTURE_LAYOUT_ID,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    return CapturedMemory(regions, header), header


def parse_capture(path: Path) -> tuple[CapturedMemory, dict]:
    return parse_capture_bytes(Path(path).read_bytes(), Path(path).as_posix())


# ---------------------------------------------------------------------------
# 实体结构与组件行：**本文件自己**的遍历
# ---------------------------------------------------------------------------
class EntityReader:
    """按冻结布局走实体组件结构。全部用 ``CapturedMemory``，越界即失败。"""

    def __init__(self, memory: CapturedMemory, layout: dict) -> None:
        self.memory = memory
        self.layout = layout
        self.notes: list[str] = []

    # --- 原语 -------------------------------------------------------------
    def _ok_ptr(self, value: int | None) -> bool:
        if value is None:
            return False
        return int(self.layout["addressLow"]) <= value < int(self.layout["addressHigh"])

    # --- 实体根 -----------------------------------------------------------
    def owner_roots(self, owner: int) -> dict:
        layout = self.layout
        owner_class = self.memory.uint64(owner + int(layout["ownerClassOffset"]))
        set_ptr = self.memory.uint64(owner + int(layout["ownerSetOffset"]))
        list_ptr = self.memory.uint64(owner + int(layout["ownerListOffset"]))
        state = self.memory.uint8(owner + int(layout["ownerStateOffset"]))
        if owner_class is None or set_ptr is None or list_ptr is None or state is None:
            raise ReadbackError(
                "readback_owner_unreadable",
                f"实体 0x{owner:x} 的根字段没有全部落在转储覆盖范围内",
            )
        if not (self._ok_ptr(owner_class) and self._ok_ptr(set_ptr) and self._ok_ptr(list_ptr)):
            raise ReadbackError(
                "readback_owner_invalid",
                f"实体 0x{owner:x} 的 class/set/list 指针不是合法地址",
            )
        if set_ptr == list_ptr:
            raise ReadbackError(
                "readback_set_list_alias",
                f"实体 0x{owner:x} 的 SET 与 LIST 指向同一地址 ⇒ 不是两套独立结构",
            )
        return {"ownerClass": owner_class, "set": set_ptr, "list": list_ptr, "state": state}

    # --- SET --------------------------------------------------------------
    def read_set(self, set_ptr: int) -> dict:
        layout = self.layout
        buckets_ptr = self.memory.uint64(set_ptr + int(layout["setBucketsOffset"]))
        slots_ptr = self.memory.uint64(set_ptr + int(layout["setSlotsOffset"]))
        count = self.memory.int32(set_ptr + int(layout["setCountOffset"]))
        last_index = self.memory.int32(set_ptr + int(layout["setLastIndexOffset"]))
        free_head = self.memory.int32(set_ptr + int(layout["setFreeHeadOffset"]))
        if count is None or last_index is None or free_head is None:
            raise ReadbackError(
                "readback_set_header_unreadable",
                f"SET=0x{set_ptr:x} 的 count/lastIndex/freeHead 没有全部被覆盖",
            )
        if count < 0 or last_index < 0 or count > last_index:
            raise ReadbackError(
                "readback_set_header_invalid",
                f"SET=0x{set_ptr:x} count={count} lastIndex={last_index} 不合法",
            )
        max_components = int(layout["maxComponents"])
        if last_index > max_components:
            raise ReadbackError(
                "readback_set_over_capacity",
                f"SET=0x{set_ptr:x} lastIndex={last_index} > 上限 {max_components}",
            )
        if not self._ok_ptr(buckets_ptr) or not self._ok_ptr(slots_ptr):
            raise ReadbackError(
                "readback_set_arrays_missing",
                f"SET=0x{set_ptr:x} 的 buckets/slots 指针缺失（count={count}）",
            )
        capacity = self.memory.uint32(buckets_ptr + int(layout["arrayLengthOffset"]))
        slot_capacity = self.memory.uint32(slots_ptr + int(layout["arrayLengthOffset"]))
        if capacity is None or slot_capacity is None:
            raise ReadbackError(
                "readback_set_capacity_unreadable",
                f"SET=0x{set_ptr:x} 的 buckets/slots 容量字段不在覆盖范围内",
            )
        if capacity != slot_capacity or capacity == 0 or capacity > max_components:
            raise ReadbackError(
                "readback_set_capacity_invalid",
                f"SET=0x{set_ptr:x} buckets={capacity} slots={slot_capacity} 上限={max_components}",
            )
        if last_index > capacity:
            raise ReadbackError(
                "readback_set_last_index_over_capacity",
                f"SET=0x{set_ptr:x} lastIndex={last_index} > capacity={capacity}",
            )
        return {
            "set": set_ptr,
            "bucketsPtr": buckets_ptr,
            "slotsPtr": slots_ptr,
            "count": count,
            "lastIndex": last_index,
            "freeHead": free_head,
            "capacity": capacity,
        }

    def _slot(self, slots_ptr: int, index: int) -> tuple[int, int, int]:
        layout = self.layout
        base = slots_ptr + int(layout["arrayElementOffset"]) + index * int(layout["slotBytes"])
        hash_value = self.memory.int32(base)
        next_index = self.memory.int32(base + 4)
        value = self.memory.int32(base + 8)
        if hash_value is None or next_index is None or value is None:
            raise ReadbackError(
                "readback_slot_unreadable",
                f"slot[{index}] @0x{base:x} 不在转储覆盖范围内",
            )
        return hash_value, next_index, value

    def walk_set_kinds(self, set_info: dict) -> list[int]:
        """沿桶链走 SET，返回 kind 列表（重复即失败）。"""
        capacity = set_info["capacity"]
        last_index = set_info["lastIndex"]
        buckets: list[int] = []
        for bucket in range(capacity):
            head = self.memory.int32(
                set_info["bucketsPtr"] + int(self.layout["arrayElementOffset"]) + bucket * 4
            )
            if head is None:
                raise ReadbackError(
                    "readback_bucket_unreadable",
                    f"bucket[{bucket}] 不在转储覆盖范围内",
                )
            buckets.append(head)
        seen = [False] * last_index
        kinds: list[int] = []
        for bucket, head in enumerate(buckets):
            # **-1 是「空桶」的哨兵**，不是非法值：合法范围是 -1 或 [1, lastIndex]。
            # 这里曾经写成 ``head < 0`` —— 与 C++ 侧同一个错误，会让任何空桶直接
            # 判非法（本地实测抓出：bucket[0] head=-1 被拒）。
            if head < -1 or head > last_index:
                raise ReadbackError(
                    "readback_bucket_head_invalid",
                    f"bucket[{bucket}] head={head} 越界（lastIndex={last_index}）",
                )
            if head == -1:
                continue
            index = head - 1
            while index != -1:
                if index < 0 or index >= last_index:
                    raise ReadbackError(
                        "readback_slot_chain_invalid",
                        f"bucket[{bucket}] 链上 index={index} 越界",
                    )
                if seen[index]:
                    raise ReadbackError(
                        "readback_slot_chain_cycle",
                        f"bucket[{bucket}] 链重复经过 slot[{index}]（环或共享）",
                    )
                seen[index] = True
                hash_value, next_index, value = self._slot(set_info["slotsPtr"], index)
                if hash_value < 0 or hash_value % capacity != bucket:
                    raise ReadbackError(
                        "readback_slot_hash_mismatch",
                        f"slot[{index}] hash={hash_value} 不属于 bucket {bucket}（capacity={capacity}）",
                    )
                if value <= 0:
                    raise ReadbackError(
                        "readback_slot_value_invalid",
                        f"slot[{index}] value={value} 不是正整数 kind",
                    )
                if value in kinds:
                    raise ReadbackError(
                        "readback_set_duplicate_kind",
                        f"SET 里出现重复 kind {value}",
                    )
                kinds.append(value)
                index = next_index
        if len(kinds) != set_info["count"]:
            raise ReadbackError(
                "readback_set_count_mismatch",
                f"SET 走链得到 {len(kinds)} 个 kind，但 count 字段说 {set_info['count']}",
            )
        free = set_info["freeHead"]
        for index in range(set_info["count"], last_index):
            if free < 0 or free >= last_index or seen[free]:
                raise ReadbackError(
                    "readback_free_list_invalid",
                    f"空闲链表在 index={index} 处非法：free={free}（lastIndex={last_index}）",
                )
            seen[free] = True
            free = self._slot(set_info["slotsPtr"], free)[1]
        if free != -1:
            raise ReadbackError(
                "readback_free_list_unterminated",
                f"空闲链表没有以 -1 结束（停在 {free}）",
            )
        if last_index and not all(seen):
            missing = [i for i, flag in enumerate(seen) if not flag]
            raise ReadbackError(
                "readback_slots_unaccounted",
                f"有 slot 既不在链上也不在空闲链表里：{missing[:8]}",
            )
        return kinds

    # --- LIST -------------------------------------------------------------
    def read_list(self, list_ptr: int) -> dict:
        layout = self.layout
        items_ptr = self.memory.uint64(list_ptr + int(layout["setBucketsOffset"]))
        count = self.memory.int32(list_ptr + int(layout["arrayLengthOffset"]))
        if count is None:
            raise ReadbackError(
                "readback_list_header_unreadable",
                f"LIST=0x{list_ptr:x} 的 count 不在转储覆盖范围内",
            )
        if count < 0 or count > int(layout["maxComponents"]):
            raise ReadbackError(
                "readback_list_count_invalid",
                f"LIST=0x{list_ptr:x} count={count}",
            )
        if not self._ok_ptr(items_ptr):
            raise ReadbackError(
                "readback_list_items_missing",
                f"LIST=0x{list_ptr:x} 的 items 指针缺失（count={count}）",
            )
        capacity = self.memory.uint32(items_ptr + int(layout["arrayLengthOffset"]))
        if capacity is None:
            raise ReadbackError(
                "readback_list_capacity_unreadable",
                f"LIST=0x{list_ptr:x} items 容量字段不在覆盖范围内",
            )
        if count > capacity or capacity > int(layout["maxComponents"]):
            raise ReadbackError(
                "readback_list_capacity_invalid",
                f"LIST=0x{list_ptr:x} count={count} capacity={capacity}",
            )
        return {"list": list_ptr, "itemsPtr": items_ptr, "count": count, "capacity": capacity}

    def read_row(self, items_ptr: int, index: int, owner: int) -> dict:
        layout = self.layout
        pointer = self.memory.uint64(items_ptr + int(layout["arrayElementOffset"]) + index * 8)
        if pointer is None:
            raise ReadbackError(
                "readback_list_element_unreadable",
                f"items[{index}] 不在转储覆盖范围内",
            )
        if not self._ok_ptr(pointer):
            raise ReadbackError(
                "readback_row_pointer_invalid",
                f"items[{index}] = 0x{pointer:x} 不是合法行地址",
            )
        wrapper = self.memory.read(pointer, int(layout["wrapperBytes"]))
        if wrapper is None:
            raise ReadbackError(
                "readback_row_unreadable",
                f"组件行 0x{pointer:x}（{int(layout['wrapperBytes'])} 字节）不在转储覆盖范围内",
            )
        wrapper_class = struct.unpack_from("<Q", wrapper, 0)[0]
        backref = struct.unpack_from("<Q", wrapper, int(layout["wrapperBackrefOffset"]))[0]
        config = struct.unpack_from("<Q", wrapper, int(layout["wrapperConfigOffset"]))[0]
        kind = struct.unpack_from("<i", wrapper, int(layout["wrapperKindOffset"]))[0]
        enabled = wrapper[int(layout["wrapperEnabledOffset"])]
        if not self._ok_ptr(wrapper_class):
            raise ReadbackError("readback_row_class_invalid", f"行 0x{pointer:x} 的 wrapper_class 非法")
        if kind <= 0:
            raise ReadbackError("readback_row_kind_invalid", f"行 0x{pointer:x} kind={kind} <= 0")
        if backref != owner:
            raise ReadbackError(
                "readback_row_backref_mismatch",
                f"行 0x{pointer:x} 的 owner 回指是 0x{backref:x}，不是实体 0x{owner:x}",
            )
        if not self._ok_ptr(config):
            raise ReadbackError("readback_row_config_invalid", f"行 0x{pointer:x} 的 config 指针非法")
        config_blob = self.memory.read(config, int(layout["setHeaderBytes"]))
        if config_blob is None:
            raise ReadbackError(
                "readback_config_unreadable",
                f"行 0x{pointer:x} 的 config 0x{config:x} 不在转储覆盖范围内",
            )
        config_class = struct.unpack_from("<Q", config_blob, 0)[0]
        config_backref = struct.unpack_from("<Q", config_blob, int(layout["configBackrefOffset"]))[0]
        config_owner = struct.unpack_from("<Q", config_blob, int(layout["configOwnerOffset"]))[0]
        if not self._ok_ptr(config_class):
            raise ReadbackError("readback_config_class_invalid", f"config 0x{config:x} 的 class 非法")
        if config_backref != pointer:
            raise ReadbackError(
                "readback_config_backref_mismatch",
                f"config 0x{config:x} 回指 0x{config_backref:x}，不是行 0x{pointer:x}",
            )
        if config_owner != owner:
            raise ReadbackError(
                "readback_config_owner_mismatch",
                f"config 0x{config:x} 的 owner 回指是 0x{config_owner:x}，不是实体 0x{owner:x}",
            )
        return {
            "index": index,
            "wrapper": pointer,
            "wrapperClass": wrapper_class,
            "config": config,
            "configClass": config_class,
            "kind": kind,
            "enabled": enabled,
        }

    def read_rows(self, list_info: dict, owner: int) -> list[dict]:
        rows = [self.read_row(list_info["itemsPtr"], index, owner)
                for index in range(list_info["count"])]
        for i, row in enumerate(rows):
            for j in range(i):
                if row["kind"] == rows[j]["kind"]:
                    raise ReadbackError(
                        "readback_duplicate_kind",
                        f"LIST 里 kind {row['kind']} 出现两次（行 {j} 与行 {i}）",
                    )
                if row["wrapper"] == rows[j]["wrapper"]:
                    raise ReadbackError(
                        "readback_duplicate_wrapper",
                        f"LIST 里同一行地址 0x{row['wrapper']:x} 出现两次",
                    )
        return rows

    # --- 全量快照 ---------------------------------------------------------
    def snapshot(self, owner: int) -> dict:
        roots = self.owner_roots(owner)
        set_info = self.read_set(roots["set"])
        list_info = self.read_list(roots["list"])
        set_kinds = self.walk_set_kinds(set_info)
        rows = self.read_rows(list_info, owner)
        if list_info["count"] != set_info["count"]:
            raise ReadbackError(
                "readback_set_list_disagree",
                f"SET count={set_info['count']} 与 LIST count={list_info['count']} 不一致",
            )
        list_kinds = sorted(row["kind"] for row in rows)
        if list_kinds != sorted(set_kinds):
            raise ReadbackError(
                "readback_set_list_kinds_disagree",
                f"SET kinds={sorted(set_kinds)} 与 LIST kinds={list_kinds} 不一致",
            )
        return {
            "owner": owner,
            "roots": roots,
            "setCount": set_info["count"],
            "setCapacity": set_info["capacity"],
            "setLastIndex": set_info["lastIndex"],
            "listCount": list_info["count"],
            "listCapacity": list_info["capacity"],
            "rowCount": len(rows),
            "kinds": sorted(list_kinds),
            "rows": rows,
        }


# ---------------------------------------------------------------------------
# 声明比对（读回的价值就在这一步）
# ---------------------------------------------------------------------------
def compare_declaration(observed: dict, declared: dict) -> list[dict]:
    """把**重推结果**与 manifest 的**声明**逐条比。返回不一致项列表。"""
    mismatches: list[dict] = []

    def check(label: str, left, right) -> None:
        if left != right:
            mismatches.append({"field": label, "observed": left, "declared": right})

    check("rowCount", observed["rowCount"], declared.get("rowCount"))
    check("listCount", observed["listCount"], declared.get("listCount"))
    check("setCount", observed["setCount"], declared.get("setCount"))
    # ``kinds`` 是**组件集合**：成员关系有意义，**顺序没有**（行序由下面的 rows[i] 逐项比）。
    # 直接比列表会把「同一集合、不同书写顺序」误判成不符 —— 实测踩过。
    observed_kinds = observed["kinds"]
    declared_kinds = declared.get("kinds")
    if declared_kinds is None:
        mismatches.append({"field": "kinds", "observed": observed_kinds, "declared": None})
    elif sorted(int(k) for k in declared_kinds) != sorted(int(k) for k in observed_kinds):
        mismatches.append({"field": "kinds", "observed": observed_kinds,
                           "declared": list(declared_kinds)})

    declared_rows = declared.get("rows") or []
    if len(declared_rows) != observed["rowCount"]:
        mismatches.append({
            "field": "rows.length",
            "observed": observed["rowCount"],
            "declared": len(declared_rows),
        })
    for index, expected in enumerate(declared_rows):
        if index >= observed["rowCount"]:
            break
        actual = observed["rows"][index]
        for key in ("kind", "wrapper", "config", "enabled", "wrapperClass", "configClass"):
            if key in expected:
                check(f"rows[{index}].{key}", actual[key], expected[key])
            else:
                mismatches.append({
                    "field": f"rows[{index}].{key}",
                    "observed": actual[key],
                    "declared": None,
                    "note": "声明缺该字段 ⇒ 无法比对，按不一致处理（fail-closed）",
                })
    return mismatches


def verify_capture(capture_path: Path, manifest_path: Path | None = None) -> tuple[dict, int]:
    """读回 + 声明比对。返回 (回执, 退出码)。"""
    try:
        memory, header = parse_capture(capture_path)
        layout = FROZEN_LAYOUTS[header["version"]]
    except ReadbackError as exc:
        return {
            "ok": False, "step": "readback-verify", "status": "rejected",
            "code": exc.code, "detail": exc.detail, "writesGameBytes": False,
        }, 2
    except OSError as exc:
        return {
            "ok": False, "step": "readback-verify", "status": "rejected",
            "code": "capture_unreadable", "detail": f"{type(exc).__name__}: {exc}",
            "writesGameBytes": False,
        }, 2

    manifest: dict | None = None
    if manifest_path is not None:
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            return {
                "ok": False, "step": "readback-verify", "status": "rejected",
                "code": "manifest_unreadable", "detail": f"{type(exc).__name__}: {exc}",
                "writesGameBytes": False,
            }, 2
        except ValueError as exc:
            return {
                "ok": False, "step": "readback-verify", "status": "rejected",
                "code": "manifest_invalid_json", "detail": str(exc),
                "writesGameBytes": False,
            }, 2
        if manifest.get("format") != MANIFEST_FORMAT:
            return {
                "ok": False, "step": "readback-verify", "status": "rejected",
                "code": "manifest_format_unknown",
                "detail": f"format={manifest.get('format')!r}，期望 {MANIFEST_FORMAT!r}",
                "writesGameBytes": False,
            }, 2
        declared_capture = manifest.get("capture") or {}
        if declared_capture.get("sha256") and declared_capture["sha256"] != header["sha256"]:
            return {
                "ok": False, "step": "readback-verify", "status": "rejected",
                "code": "capture_hash_mismatch",
                "detail": (
                    f"manifest 声明转储 sha256={declared_capture['sha256'][:16]}…，"
                    f"实际 {header['sha256'][:16]}… ⇒ 声明的不是这份字节"
                ),
                "writesGameBytes": False,
            }, 1

    owner = header["owner"]
    try:
        before = EntityReader(memory, layout).snapshot(owner)
        after = EntityReader(memory, layout).snapshot(owner)
    except ReadbackError as exc:
        return {
            "ok": False, "step": "readback-verify", "status": "rejected",
            "code": exc.code, "detail": exc.detail,
            "capture": header, "writesGameBytes": False,
        }, 1

    # 两次独立遍历必须给出同一答案（本文件自己的稳定性检查）。
    if before != after:
        return {
            "ok": False, "step": "readback-verify", "status": "rejected",
            "code": "readback_unstable",
            "detail": "对同一份只读字节的两次独立遍历结果不同 ⇒ 读回实现有问题",
            "capture": header, "writesGameBytes": False,
        }, 1

    result: dict = {
        "ok": False,
        "step": "readback-verify",
        "tool": TOOL,
        "toolVersion": TOOL_VERSION,
        "module": MODULE,
        "contractVersion": CONTRACT_VERSION,
        "capture": header,
        "capturePath": Path(capture_path).as_posix(),
        "observed": {
            "owner": f"0x{owner:x}",
            "ownerClass": f"0x{before['roots']['ownerClass']:x}",
            "set": f"0x{before['roots']['set']:x}",
            "list": f"0x{before['roots']['list']:x}",
            "rowCount": before["rowCount"],
            "kinds": before["kinds"],
            "rows": [
                {
                    "index": row["index"],
                    "kind": row["kind"],
                    "wrapper": f"0x{row['wrapper']:x}",
                    "config": f"0x{row['config']:x}",
                    "enabled": row["enabled"],
                }
                for row in before["rows"]
            ],
        },
        "independence": {
            "importsMounter": False,
            "reparsesRawCapture": True,
            "layoutSource": f"FROZEN_LAYOUTS[{header['version']}] in this file",
            "statement": (
                "本读回按**本文件自己冻结的**布局常量重走实体结构（SET 与 LIST 两套独立读、"
                "逐行读 wrapper/config 并核对三处回指），**不 import 写入器**。"
                "manifest 只用于**比对**，不用于提供观测。"
            ),
        },
        "writesGameBytes": False,
    }

    if manifest is None:
        result.update({"ok": True, "status": "read_back_only",
                       "note": "只做了读回，没有 manifest 可比对 ⇒ 不作任何一致性结论"})
        return result, 0

    declared = manifest.get("declared") or {}
    mismatches = compare_declaration(before, declared)
    result["declared"] = declared
    result["declarationMismatches"] = mismatches
    result["before"] = manifest.get("before")
    result["manifestPath"] = Path(manifest_path).as_posix()

    # 前缀不变性：manifest 声称 before 是 k 行、after 是 k+1 行且前缀逐字节不变。
    # 这里用**捕获里的真实行**去核对 before 声明，而不是相信它。
    before_declared = manifest.get("before") or {}
    before_rows = before_declared.get("rows")
    prefix_problems: list[dict] = []
    if before_rows is None:
        prefix_problems.append({
            "field": "before.rows",
            "observed": "present",
            "declared": None,
            "note": "manifest 没给 before.rows ⇒ 无法核对前缀不变性（fail-closed）",
        })
    else:
        if len(before_rows) + 1 != before["rowCount"]:
            prefix_problems.append({
                "field": "before.rows.length + 1",
                "observed": before["rowCount"],
                "declared": len(before_rows),
            })
        for index, row in enumerate(before_rows):
            if index >= before["rowCount"]:
                break
            actual = before["rows"][index]
            for key in ("kind", "wrapper", "config", "enabled"):
                if key in row and actual[key] != row[key]:
                    prefix_problems.append({
                        "field": f"before.rows[{index}].{key}",
                        "observed": actual[key],
                        "declared": row[key],
                        "note": "前缀被改动 ⇒ 本次写入不是「只追加」",
                    })
    result["prefixProblems"] = prefix_problems

    result["status"] = "accepted" if not mismatches and not prefix_problems else "rejected"
    result["ok"] = result["status"] == "accepted"
    if not result["ok"]:
        result["code"] = "declaration_mismatch"
        result["detail"] = (
            f"{len(mismatches)} 条声明与重推结果不符、{len(prefix_problems)} 条前缀问题；"
            "读回**不**跟着声明走"
        )
    return result, (0 if result["ok"] else 1)


def rederive_append_pair(before_capture: Path, after_capture: Path) -> dict:
    """**逐字节重算**一次「追加式挂载」的三件事，不给调用方抄结论的机会。

    输入是**两份独立的 MWCAP**（各覆盖一次挂载的读数窗口）：

    * ``before_capture`` —— 挂载**之前**那一刻的快照；
    * ``after_capture``  —— 挂载**之后**那一刻的快照（新增了一行）。

    重算：
    1. **变更**：after 行数 == before 行数 + 1；
    2. **前缀 / 既有成员保全**：before 的**每一行**（wrapper 地址 + kind +
       config + enabled + 两个 class）都能在 after 的前 ``before.rowCount`` 行里
       **逐字段找到**（不是只比行数）⇒ 原有组件一个不少、不被顶掉；
    3. **返回 after 侧新增行的完整身份**，供调用方与 spec 声明逐项比对。

    解码只用本文件**自己的**冻结布局；**不 import** 写入器，也不读任何生成器总结。
    """
    before_mem, before_hdr = parse_capture(Path(before_capture))
    after_mem, after_hdr = parse_capture(Path(after_capture))
    before = EntityReader(before_mem, FROZEN_LAYOUTS[before_hdr["version"]]).snapshot(
        before_hdr["owner"])
    after = EntityReader(after_mem, FROZEN_LAYOUTS[after_hdr["version"]]).snapshot(
        after_hdr["owner"])

    problems: list[dict] = []
    if before_hdr["owner"] != after_hdr["owner"]:
        problems.append({"field": "owner", "observed": after_hdr["owner"],
                         "declared": before_hdr["owner"],
                         "why": "两份捕获不是同一个实体"})

    delta = after["rowCount"] - before["rowCount"]
    if delta != 1:
        problems.append({"field": "rowCountDelta", "observed": delta, "declared": 1,
                         "why": "追加式挂载必须恰好 +1"})

    prefix_problems: list[dict] = []
    for index, old in enumerate(before["rows"]):
        if index >= after["rowCount"]:
            prefix_problems.append({"field": f"rows[{index}]", "observed": None,
                                    "declared": old["kind"],
                                    "why": "既有行在 after 里不见了"})
            continue
        new = after["rows"][index]
        for key in ("kind", "wrapper", "config", "enabled", "wrapperClass", "configClass"):
            if old[key] != new[key]:
                prefix_problems.append({
                    "field": f"rows[{index}].{key}", "observed": new[key],
                    "declared": old[key],
                    "why": "既有成员被改动/顶掉（前缀不守恒）",
                })

    added = None
    if delta == 1 and after["rowCount"] > before["rowCount"]:
        added = after["rows"][before["rowCount"]]

    return {
        "beforeOwner": before_hdr["owner"],
        "afterOwner": after_hdr["owner"],
        "beforeRowCount": before["rowCount"],
        "afterRowCount": after["rowCount"],
        "beforeKinds": before["kinds"],
        "afterKinds": after["kinds"],
        "delta": delta,
        "addedRow": added,
        "problems": problems,
        "prefixProblems": prefix_problems,
        # **重算出来的三个判定**（调用方必须用这三个，不许抄 summary）
        "mutationVerified": bool(delta == 1 and added is not None and not problems),
        "prefixPreserved": not prefix_problems,
        "readsOnlyBytes": True,
    }


# ---------------------------------------------------------------------------
# 自检（fail-closed）
# ---------------------------------------------------------------------------
def _selftest() -> tuple[dict, int]:
    checks: list[dict] = []

    def note(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    source = Path(__file__).read_text(encoding="utf-8")
    try:
        compile(source, str(Path(__file__)), "exec")
        note("python_compiles", True, "compile() 通过")
    except SyntaxError as exc:  # pragma: no cover
        note("python_compiles", False, f"SyntaxError: {exc}")

    # **独立性实测**：源码里不许出现对写入器的 import。
    forbidden = [
        line for line in source.splitlines()
        if ("component_mounter" in line or "component_attach" in line)
        and (line.strip().startswith("import ") or line.strip().startswith("from "))
    ]
    note("does_not_import_mounter", not forbidden,
         "无 import 写入器" if not forbidden else f"出现：{forbidden[:3]}")

    # 布局与写入器声明的一致性：由 mounter 侧比对（本文件不反向 import）。

    # 解析器对**故意损坏的**输入必须拒绝。全程在内存里，不写任何文件。
    def roundtrip(payload: bytes) -> tuple[str, str]:
        try:
            parse_capture_bytes(payload, "selftest")
            return "ACCEPTED", ""
        except ReadbackError as exc:
            return "REFUSED", exc.code

    header = CAPTURE_MAGIC + struct.pack("<IIQI", 1, 0, 0x10000, 1)
    status, code = roundtrip(header)
    note("empty_capture_accepted", status == "ACCEPTED", f"{status} {code}")

    status, code = roundtrip(b"NOTMWCAP" + header[8:])
    note("bad_magic_refused", status == "REFUSED" and code == "capture_bad_magic", code)

    status, code = roundtrip(CAPTURE_MAGIC + struct.pack("<IIQI", 99, 0, 0x10000, 1))
    note("future_version_refused", status == "REFUSED" and code == "capture_version_unsupported", code)

    status, code = roundtrip(CAPTURE_MAGIC + struct.pack("<IIQI", 1, 5, 0x10000, 1))
    note("record_count_overrun_refused",
         status == "REFUSED" and code == "capture_record_truncated", code)

    status, code = roundtrip(header + b"\x00" * 3)
    note("trailing_bytes_refused",
         status == "REFUSED" and code == "capture_trailing_bytes", code)

    # 同一地址两次读到不同内容 ⇒ 必须拒绝（捕获期不稳定）。
    # 必须声明 records=2，否则解析器在第一条记录后就发现「有字节未被解释」并更早拒绝。
    unstable = (CAPTURE_MAGIC + struct.pack("<IIQI", 1, 2, 0x10000, 1)
                + struct.pack("<QI", 0x10000, 4) + b"AAAA"
                + struct.pack("<QI", 0x10000, 4) + b"BBBB")
    status, code = roundtrip(unstable)
    note("unstable_region_refused",
         status == "REFUSED" and code == "capture_region_unstable", code)

    # 越界读必须返回 None（不补零）—— 这是「读回成功 ⇒ 字节确实存在」的基础。
    memory, _ = parse_capture_bytes(
        CAPTURE_MAGIC + struct.pack("<IIQI", 1, 1, 0x10000, 1)
        + struct.pack("<QI", 0x10000, 8) + b"\x01" * 8, "selftest"
    )
    note("out_of_cover_read_returns_none", memory.read(0x10008, 1) is None,
         "覆盖范围外的读返回 None（不补零）")
    note("in_cover_read_returns_bytes", memory.read(0x10000, 8) == b"\x01" * 8,
         "覆盖范围内的读返回真实字节")
    note("covered_region_meta", memory.regionCount == 1 and memory.coveredBytes == 8,
         f"regions={memory.regionCount} bytes={memory.coveredBytes}")

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok, "step": "readback-selftest", "tool": TOOL, "toolVersion": TOOL_VERSION,
        "module": MODULE, "contractVersion": CONTRACT_VERSION,
        "checks": checks, "passed": sum(1 for c in checks if c["ok"]), "total": len(checks),
        "writesGameBytes": False,
        "honestLimits": [
            "自检不是通过证据（contract v26 moduleSelfCheckPolicy）。",
            "本文件不产生转储，也不碰游戏：它只读文件。",
        ],
    }, (0 if ok else 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="readback.py",
        description="combat-encounters 独立读回：从 MWCAP 原始转储重推实体组件，再与声明比对。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("verify", help="读回一份转储；给了 manifest 就同时比对声明")
    p.add_argument("--capture", required=True, help="MWCAP 原始转储路径")
    p.add_argument("--manifest", default=None, help="manifest.json（可选；给了才做一致性结论）")
    p.set_defaults(func=lambda a: _run_verify(a))

    p = sub.add_parser("selftest", help="fail-closed 自检")
    p.set_defaults(func=lambda a: _run_selftest(a))

    p = sub.add_parser("layout", help="打印本文件冻结的布局（供人工核对）")
    p.set_defaults(func=lambda a: _run_layout(a))

    args = parser.parse_args(argv)
    return int(args.func(args))


def _run_verify(args) -> int:
    result, code = verify_capture(Path(args.capture),
                                 Path(args.manifest) if args.manifest else None)
    _emit(result)
    return code


def _run_selftest(args) -> int:
    result, code = _selftest()
    _emit(result)
    return code


def _run_layout(args) -> int:
    _emit({
        "ok": True, "step": "layout", "tool": TOOL,
        "frozenLayouts": {str(k): v for k, v in FROZEN_LAYOUTS.items()},
        "captureFormat": CAPTURE_FORMAT, "headerBytes": CAPTURE_HEADER_BYTES,
        "writesGameBytes": False,
    })
    return 0


if __name__ == "__main__":  # pragma: no cover - runner entry
    raise SystemExit(main())
