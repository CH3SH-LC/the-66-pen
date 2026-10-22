#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""combat-encounters: 原生挂载**写入器**（write side）+ 可被 runner 调用的 argv。

本文件是 combat 模块对 world-contract v26 `componentWriterBoundary` 的落实：
「白名单可以扩展，扩展属实现工作」。它**不修改**任何既有文件，尤其是
``tools/game-executor/template-authoring/component_attachment.{h,cpp}``
（那里的 ``{17,33,35}`` 白名单属于 native-options 的写范围；本目录独立实现）。

=============================================================================
0. 这一版到底是「真实写入路径」还是「又一个回执模型」
=============================================================================
判定标准是**装配面里有没有真的发出那一次调用**。本文件的答案：

* **有** —— 本文件生成一份**自足、可编译的 C++ 翻译单元**，里面的
  ``MounterRun`` 真的通过函数指针发起一次 ``attach(owner, kind)`` 调用，
  调用前后各自做一次全量读回，并（仅当真的调用了）落一份**原始内存转储**。
* **证据是可执行的**：生成的 TU 在本机 MSVC 19.44 下 ``/c`` 编译通过，
  并在 ``--driver`` 生成的驱动里对**真实可写内存**跑完 12 条断言
  （含正常挂载、幂等、身份不符、前缀被改、返回空、抛异常、未知 kind、
  哨兵 kind、锚点缺失）。
* **它仍然不是「游戏里挂上了」** —— 见下。

**本文件不声称的事（重要，不许当成已完成）**：
  本机证据是 **MSVC 编译 + 进程内真实内存（驱动自建桩）**。
  **没有**注入游戏进程、**没有**读游戏内存、**没有**任何游戏写入。
  world-contract v26 ``executionBoundaries.nativeWrites`` 把游戏原生读写
  划给 leader 独占串行窗口 ⇒ 那个窗口属于 root，不属于本模块。
  游戏内是否真的挂得上，只有 leader 在独占窗口里跑
  ``mounter --emit-tu`` → 编译 → 注入 → ``readback --capture`` 才能定。

=============================================================================
1. fail-closed：**缺 ABI 锚点即拒绝执行，绝不写死地址**
=============================================================================
本工程纪律：原生地址是**构建的函数**（删链的旧锚 ``0xcb64140`` 已作废、
``0xcba3130`` 是重推导结果）。因此本文件**不把任何地址写死进代码**：

* 地址以 ``Anchor`` 形式存放（``{rva, head32, imageSha256, provenance}``）；
* ``resolve_anchors()`` 在**发出任何请求之前**用**磁盘上的真实 PE** 复核四件事：
  ① 镜像 sha256 与锚点声明一致；② RVA 能唯一映射到节区；③ 该处**前 32 字节**
  与 ``head32`` 逐字节相等；④ 映射唯一（歧义即拒绝）。
* 任一不成立 ⇒ ``MounterError('ABI_ANCHOR_*')``，**不产出 TU、不产出卡**。
* ``resolve_anchors(require=('ATTACH',), allow_rva_literals=False)`` 里
  ``allow_rva_literals`` 是**反向控制**：置 True 时把 ``head32`` 丢掉，
  解析必须**失败**。生产路径永远是 False。

锚点**不抄写在源码里**，而是从既有运行时档案读取并由镜像哈希钉死 ——
``tools/game-executor/native-options/runtime-profile.json`` 的
``functions[]``（含 ``attach`` 在 ``0x867c610`` 的 ``head32`` 与 ``imageSha256``）。
这是**读取一个已发布的、构建绑定的锚点集**，不是本文件猜地址。

本节实测（2026-10-17，只读）：磁盘镜像
``D:\\games\\Genshin Impact Game\\YuanShen.exe`` sha256 =
``7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e``，
与档案 ``imageSha256`` **相等**；``0x867c610`` 前 32 字节与档案 ``head32``
**逐字节相等**；``rva+1`` 的**阳性对照**不等（证明比较真的在比）。

=============================================================================
2. kind 面：46 项**封闭**枚举，但「枚举宽度 ≠ 已跑过」
=============================================================================
``COMPONENT_KINDS`` 由
``.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs``
的 46 个成员逐字抄录（45 个真成员 + ``Arraysize=47`` 哨兵）。
**哨兵不是组件 kind**，具名拒绝 ``sentinel_is_not_a_component``。

枚举宽度**不等于**「我们已经跑过这个 kind」。本文件按 kind 三分：

* ``PROVEN_ATTACH_KINDS = {17,33,35}`` —— 唯一有**既有原生实现**为据的 kind
  （``component_attachment.cpp:172-173``）；
* ``EXECUTABLE_KINDS`` —— 本文件生成的分支允许的 kind（默认 = 整个 45 项
  真成员，可用 ``--kinds`` 收窄）。**允许发出 ≠ 已跑过**；
* ``KIND_RUN_LEDGER`` —— **本模块亲自跑过的 kind**。截至本版是**空的**，
  因为游戏原生窗口属 leader 独占。空账本会在 TU 里生成
  ``kKindRunLedgerEmpty = true``，并在回执里写明。

=============================================================================
3. 与 readback.py 的分工（独立读回）
=============================================================================
本文件写出的东西**不是**成功声明，而是**原始内存转储 + 声明**：

* ``MWCAP`` 原始转储：**恰好是写入器真正读过的字节**（读 + 捕获同一次调用），
  含地址表；格式自描述、无省略；
* ``manifest.json``：写了什么 / 观察到什么 / 布局版本 / 镜像哈希。

``readback.py`` **不 import 本文件**，只吃 ``MWCAP``，自己按冻结布局常量
重走一遍结构（SET 与 LIST 两套独立读、逐行读 wrapper/config、回指核对），
再与 manifest 的**声明**比对。**声明错了就读回失败** —— 那才是独立读回，
不是「再信一次回执」。两条命令的契约见各自 ``--help``。

=============================================================================
4. 依赖树（可核查）
=============================================================================
只读依赖（本文件**只读**、不写）：
  * ``tools/game-executor/native-options/runtime-profile.json`` —— 锚点集
  * ``tools/game-executor/template-authoring/component_attachment.h`` —— ABI 签名出处
  * ``.runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs`` —— 枚举出处
  * ``data/mondstadt/world-contract.json`` —— 契约版本
  * ``D:\\games\\Genshin Impact Game\\YuanShen.exe`` —— **只读**，仅用于锚点复核
被 ``--check-deps`` 复核；输出含每项的 sha256、是否被本工具写过、
以及「本工具是否改过 component_attachment.*」的实测答案。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]

MODULE = "combat-encounters"
TOOL = "component-mounter"
TOOL_VERSION = 1
CONTRACT_VERSION = 26

#: 转储格式版本。readback.py 按版本号选它**自己冻结的**布局常量；
#: 本工具升版本而 readback 没有对应常量 ⇒ readback 必须具名拒绝（fail-closed）。
CAPTURE_FORMAT = "MWCAP"
CAPTURE_VERSION = 1
CAPTURE_LAYOUT_ID = "component-attachment-native-v1"

DEFAULT_IMAGE = Path(r"C:\Games\Genshin Impact Game\YuanShen.exe")
RUNTIME_PROFILE = Path("tools/game-executor/native-options/runtime-profile.json")
SHARED_ABI_HEADER = Path("tools/game-executor/template-authoring/component_attachment.h")
KIND_ENUM_SOURCE = Path(
    ".runtime/editor-catalog/resolved/QbNEoK0CioqD9L4tX6TA.jaUof90C3Ncl5BAJri4x.cs"
)
WORLD_CONTRACT = Path("data/mondstadt/world-contract.json")


class MounterError(RuntimeError):
    """具名拒绝。每条都带 ``code``，绝不静默降级。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        return {"ok": False, "code": self.code, "detail": self.detail}


# ---------------------------------------------------------------------------
# 组件 kind：46 项封闭枚举（抄自上述 .cs，逐字；数字与名字一一对应）
# ---------------------------------------------------------------------------
COMPONENT_KINDS: dict[str, int] = {
    "BeyondCompTypeNone": 0,
    "BeyondCompTypeCustomValue": 1,
    "BeyondCompTypeTimer": 3,
    "BeyondCompTypeMover": 4,
    "BeyondCompTypeClientTrigger": 5,
    "BeyondCompTypeEffect": 6,
    "BeyondCompTypeBornPoint": 7,
    "BeyondCompTypeCollision": 8,
    "BeyondCompTypeFollowMove": 9,
    "BeyondCompTypeBulletMove": 11,
    "BeyondCompTypeHitDetection": 12,
    "BeyondCompTypeCamera": 13,
    "BeyondCompTypeRoleStatus": 14,
    "BeyondCompTypeAvatarDisturber": 15,
    "BeyondCompTypeCountDown": 16,
    "BeyondCompTypeOption": 17,
    "BeyondCompTypeCombat": 18,
    "BeyondCompTypeHitbox": 19,
    "BeyondCompTypeBulletPattern": 20,
    "BeyondCompTypeTempAttachPoint": 21,
    "BeyondCompTypeCustomSkill": 22,
    "BeyondCompTypeIntee": 23,
    "BeyondCompTypeMpAction": 24,
    "BeyondCompTypeTag": 25,
    "BeyondCompTypeEnmity": 26,
    "BeyondCompTypeNameplate": 27,
    "BeyondCompTypeTalk": 28,
    "BeyondCompTypeSoundEffect": 29,
    "BeyondCompTypeMonsterPatrol": 30,
    "BeyondCompTypeLevelStateMachine": 31,
    "BeyondCompTypeMinimapMark": 32,
    "BeyondCompTypeStuffBag": 33,
    "BeyondCompTypeEquipStuffBag": 34,
    "BeyondCompTypeShop": 35,
    "BeyondCompTypeDropGather": 36,
    "BeyondCompTypeDropStuff": 37,
    "BeyondCompTypeLightGroup": 38,
    "BeyondCompTypeScanEntity": 39,
    "BeyondCompTypePopUp": 40,
    "BeyondCompTypeObstacle": 41,
    "BeyondCompTypeMonsterAiComp": 42,
    "BeyondCompTypeWaterfallComp": 43,
    "BeyondCompTypeWaterCubeComp": 44,
    "BeyondCompTypeCursorCollision": 45,
    "BeyondCompTypeVehicle": 46,
    "BeyondCompTypeArraysize": 47,  # 哨兵，不是组件
}

KIND_SENTINEL = COMPONENT_KINDS["BeyondCompTypeArraysize"]

_KIND_TO_NAME = {value: name for name, value in COMPONENT_KINDS.items()}

#: 有**既有原生实现**为据的 kind（``component_attachment.cpp:172-173`` 的 ``{17,33,35}``）。
PROVEN_ATTACH_KINDS = frozenset({17, 33, 35})

#: combat 模块在本轮点名的 kind（`component_attach.py` 的 NEEDED_KINDS，同名同值）。
COMBAT_NEEDED_KINDS: dict[str, int] = {
    "hitbox": COMPONENT_KINDS["BeyondCompTypeHitbox"],
    "enmity": COMPONENT_KINDS["BeyondCompTypeEnmity"],
    "nameplate": COMPONENT_KINDS["BeyondCompTypeNameplate"],
    "monster_patrol": COMPONENT_KINDS["BeyondCompTypeMonsterPatrol"],
    "drop_stuff": COMPONENT_KINDS["BeyondCompTypeDropStuff"],
    "monster_ai": COMPONENT_KINDS["BeyondCompTypeMonsterAiComp"],
}

# ---------------------------------------------------------------------------
# 逐 kind 的 owner / class / fields 证据台账 —— **禁止按 kind 枚举直接放行**
# ---------------------------------------------------------------------------
#: 挂任何 kind 之前必须逐一核实**真实的 owner / class / fields**（协调者硬规则）。
#: 本台账只登记**有出处**的核实结果；没有证据的 kind 一律 ``UNRESOLVED``，
#: 并且 ``require_kind_evidence()`` 会对它**具名拒绝**——枚举宽度不构成放行理由。
#:
#: ``hasBeenRun`` 是**本模块亲自在真实引擎里跑过**的记录。到今天为止全部为 False
#: （游戏原生窗口属 leader 独占），所以这张表不能当作「已跑过」的证据。
KIND_EVIDENCE_LEDGER: dict[int, dict] = {
    17: {"status": "PROVEN", "ownerClassFields": "shared primitive", "hasBeenRun": False,
         "source": "tools/game-executor/template-authoring/component_attachment.cpp:172-173 "
                   "({17,33,35} whitelist) + native-options/native_tabs.cpp:67 call site"},
    33: {"status": "PROVEN", "ownerClassFields": "shared primitive", "hasBeenRun": False,
         "source": "tools/game-executor/template-authoring/component_attachment.cpp:172-173"},
    35: {"status": "PROVEN", "ownerClassFields": "shared primitive", "hasBeenRun": False,
         "source": "tools/game-executor/template-authoring/component_attachment.cpp:172-173"},
    # combat 点名的六个 kind：**kind 号已确证，但 owner/class/fields 未实测**。
    19: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": ".runtime/editor-catalog/.../jaUof90C3Ncl5BAJri4x.cs:22 (kind 号)",
         "missing": "真实 owner / wrapper_class / config_class / fields 未逐条核实"},
    26: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": "kind 号 + data/mondstadt/combat/prefab-components.json 的 kind 记录；"
                   "**prefab 记录只给 kind，不给 class/fields**",
         "missing": "owner / class / fields 未逐条核实"},
    27: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": "kind 号（.cs:24）", "missing": "owner / class / fields 未逐条核实"},
    30: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": "kind 号（.cs:27）", "missing": "owner / class / fields 未逐条核实"},
    37: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": "kind 号（.cs:40）；life 模块已证 kind=37 但 config 布局未确证",
         "missing": "owner / class / fields 未逐条核实；config 布局未确证"},
    42: {"status": "UNRESOLVED", "hasBeenRun": False,
         "source": "kind 号（.cs:49）", "missing": "owner / class / fields 未逐条核实"},
}


def kind_evidence(kind: int) -> dict:
    kind = int(kind)
    entry = KIND_EVIDENCE_LEDGER.get(kind)
    if entry is None:
        return {"kind": kind, "name": component_kind_name(kind), "status": "UNRESOLVED",
                "hasBeenRun": False,
                "missing": "该 kind 不在证据台账里；**没有证据不得放行**"}
    return dict(entry, kind=kind, name=component_kind_name(kind))


def require_kind_evidence(kind: int, *, executable_without_evidence: bool) -> dict:
    """逐 kind 证据闸。

    ``executable_without_evidence`` 默认 **False**。置 True 时放行无证据 kind，
    但必须**显式**这么做，且回执里会带上 ``evidenceGateBypassed``。
    生产路径永远是 False —— 「kind 在枚举里」**不是**核实。
    """
    entry = kind_evidence(kind)
    if entry["status"] != "PROVEN" and not executable_without_evidence:
        raise MounterError(
            "KIND_OWNER_CLASS_FIELDS_UNRESOLVED:" + str(int(kind)),
            f"kind {int(kind)}（{entry['name']}）的 owner/class/fields 未经逐条核实"
            f"（{entry.get('missing', '')}）。**禁止按 kind 枚举直接放行**；"
            "要么逐条核实后登记进 KIND_EVIDENCE_LEDGER，要么显式 --allow-unverified-kinds"
            "（回执会标 evidenceGateBypassed=true）",
        )
    return entry

#: 全 45 项真成员（去掉哨兵）＝本文件 TU 默认允许发出的 kind 集合。
DEFAULT_EXECUTABLE_KINDS: tuple[int, ...] = tuple(
    sorted(v for k, v in COMPONENT_KINDS.items() if v != KIND_SENTINEL)
)

#: **本模块亲自跑过的 kind 账本**。游戏原生窗口属 leader 独占（contract v26
#: executionBoundaries.nativeWrites）⇒ 开发期为零。空账本会写进 TU 与回执。
KIND_RUN_LEDGER: dict[int, dict] = {}


def component_kind_name(kind: int) -> str:
    return _KIND_TO_NAME.get(int(kind), f"kind-{int(kind)}")


def require_executable_kind(kind: int, allowed: Iterable[int]) -> int:
    """kind 闸。顺序：哨兵 → 枚举 → 本次允许集合。"""
    kind = int(kind)
    if kind == KIND_SENTINEL:
        raise MounterError(
            "sentinel_is_not_a_component",
            f"kind {KIND_SENTINEL} 是 BeyondCompTypeArraysize 哨兵，不是组件 kind",
        )
    if kind not in _KIND_TO_NAME:
        raise MounterError(
            "unknown_component_kind",
            f"kind {kind} 不在 46 项封闭枚举里（枚举是白名单，未列入者不是组件）",
        )
    allowed_set = {int(k) for k in allowed}
    if kind not in allowed_set:
        raise MounterError(
            "kind_not_in_executable_set",
            f"kind {kind}（{component_kind_name(kind)}）不在本次允许集合 "
            f"{sorted(allowed_set)} 里；枚举宽度 ≠ 支持（ENUM-WIDTH-IS-NOT-SUPPORT）",
        )
    return kind


# ---------------------------------------------------------------------------
# ABI 锚点
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Anchor:
    """一个**构建绑定**的锚点。地址永远是构建的函数，必须每次对磁盘复核。"""

    name: str
    rva: int
    head32: str
    image_sha256: str
    metadata_flags: tuple[str, ...]
    guards: tuple[str, ...]
    provenance: str

    def head_bytes(self) -> bytes:
        return bytes.fromhex(self.head32)


@dataclass(frozen=True)
class AnchorCheck:
    name: str
    rva: str
    declared_head32: str
    observed_head32: str
    mapped_offset: int
    mapping_count: int
    image_sha256: str

    @property
    def ok(self) -> bool:
        return (
            self.mapping_count == 1
            and self.declared_head32 == self.observed_head32
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pe_sections(data: bytes) -> tuple[list[tuple[int, int, int, int]], int]:
    """返回 (sections, sizeOfImage)。sections 项 = (name_rva, virtual_addr, vsize, raw_ptr)。"""
    if len(data) < 64 or data[:2] != b"MZ":
        raise MounterError("INVALID_DOS_HEADER", "镜像不是 PE（无 MZ）")
    pe = struct.unpack_from("<I", data, 60)[0]
    if not (64 <= pe <= len(data) - 264) or data[pe:pe + 4] != b"PE\0\0":
        raise MounterError("INVALID_PE_HEADER", f"e_lfanew=0x{pe:x} 处不是 PE\\0\\0")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    size_opt = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    if not (1 <= count <= 96 and size_opt >= 112 and opt + size_opt + count * 40 <= len(data)):
        raise MounterError("INVALID_PE_SECTIONS", f"节区表越界（count={count}）")
    size_image = struct.unpack_from("<I", data, opt + 56)[0]
    sections = [
        struct.unpack_from("<IIII", data, opt + size_opt + i * 40 + 8)
        for i in range(count)
    ]
    return sections, size_image


def _rva_offsets(sections, rva: int, length: int, total: int) -> list[int]:
    return [
        raw + rva - va
        for _n, va, vsize, raw in sections
        if va <= rva and rva + length <= va + vsize and raw + rva - va + length <= total
    ]


def load_runtime_anchors(profile_path: Path = RUNTIME_PROFILE) -> tuple[dict[str, Anchor], str, str]:
    """抽 ``attach`` 锚点。返回 (anchors, image_sha256, profile_sha256)。

    只取**档案真有的**锚点；档案里没有的名字**不会**被凭空造出来。
    """
    path = profile_path if profile_path.is_absolute() else REPO_ROOT / profile_path
    if not path.is_file():
        raise MounterError("ABI_PROFILE_MISSING", f"锚点档案不存在：{path}")
    raw = path.read_bytes()
    profile = json.loads(raw.decode("utf-8-sig"))
    image_sha = str(profile.get("imageSha256") or "")
    if len(image_sha) != 64:
        raise MounterError(
            "ABI_PROFILE_NO_IMAGE_HASH",
            f"{path} 的 imageSha256 缺失/长度非 64 ⇒ 无法把锚点绑到构建上",
        )
    anchors: dict[str, Anchor] = {}
    for entry in profile.get("functions") or []:
        rva_text = str(entry.get("rva") or "")
        head = str(entry.get("head32") or "")
        if not rva_text or len(head) != 64:
            continue
        try:
            rva = int(rva_text, 16)
        except ValueError:
            continue
        name = {0x867C610: "ATTACH"}.get(rva)
        if name is None:
            continue
        anchors[name] = Anchor(
            name=name,
            rva=rva,
            head32=head,
            image_sha256=image_sha,
            metadata_flags=tuple(str(x) for x in (entry.get("metadataFlags") or [])),
            guards=tuple(str(x) for x in (entry.get("guards") or [])),
            provenance=(
                f"{RUNTIME_PROFILE.as_posix()} functions[rva={rva_text}] "
                "(head32) + imageSha256；ABI 签名出处 "
                f"{SHARED_ABI_HEADER.as_posix()}:7 "
                "'using AttachComponent = void* (__cdecl *)(void* owner, std::int32_t kind); // 867c610'"
            ),
        )
    return anchors, image_sha, hashlib.sha256(raw).hexdigest()


def resolve_anchors(
    *,
    image_path: Path = DEFAULT_IMAGE,
    profile_path: Path = RUNTIME_PROFILE,
    require: Sequence[str] = ("ATTACH",),
    allow_rva_literals: bool = False,
) -> dict:
    """**发出任何请求之前**的锚点解析。任一条不成立即具名拒绝（fail-closed）。

    ``allow_rva_literals=True`` 是**反向控制**：丢掉 head32 后解析必须失败。
    生产路径永远 False；它存在的唯一目的是让自检能证明这个闸真的会关。
    """
    anchors, profile_image_sha, profile_sha = load_runtime_anchors(profile_path)
    missing = [name for name in require if name not in anchors]
    if missing:
        raise MounterError(
            "ABI_ANCHOR_NOT_DERIVED",
            f"锚点 {missing} 在 {profile_path} 里不存在；缺锚点**不得**写死地址，"
            "必须为**本构建**重新推导并记录后才允许发请求",
        )

    if not image_path.is_file():
        raise MounterError(
            "ABI_ANCHOR_IMAGE_MISSING",
            f"目标镜像不存在：{image_path}；没有磁盘镜像就**无法**把 RVA 复核到构建上",
        )
    data = image_path.read_bytes()
    image_sha = hashlib.sha256(data).hexdigest()

    checks: list[AnchorCheck] = []
    sections, size_image = _pe_sections(data)
    for name in require:
        anchor = anchors[name]
        declared = "" if allow_rva_literals else anchor.head32
        expected = anchor.head_bytes() if declared else b""
        length = 32 if expected else 1
        offsets = _rva_offsets(sections, anchor.rva, length, len(data))
        observed = ""
        if len(offsets) == 1:
            observed = data[offsets[0]:offsets[0] + length].hex()
        checks.append(
            AnchorCheck(
                name=name,
                rva=f"0x{anchor.rva:x}",
                declared_head32=declared,
                observed_head32=observed,
                mapped_offset=offsets[0] if len(offsets) == 1 else -1,
                mapping_count=len(offsets),
                image_sha256=image_sha,
            )
        )

    bad_mapping = [c for c in checks if c.mapping_count != 1]
    if bad_mapping:
        raise MounterError(
            "ABI_ANCHOR_RVA_UNMAPPED",
            "RVA 必须**唯一**映射到节区："
            + ", ".join(f"{c.name}@ {c.rva} count={c.mapping_count}" for c in bad_mapping),
        )

    drifted = [c for c in checks if not c.ok]
    if drifted:
        raise MounterError(
            "ABI_ANCHOR_BUILD_DRIFT",
            "锚点字节与磁盘镜像不符（构建已变）："
            + ", ".join(f"{c.name}@ {c.rva}" for c in drifted)
            + "；地址是构建的函数，必须为**新构建**重新推导后重试",
        )

    if image_sha != profile_image_sha:
        raise MounterError(
            "ABI_ANCHOR_IMAGE_HASH_MISMATCH",
            f"磁盘镜像 sha256={image_sha[:16]}… 与档案 imageSha256="
            f"{profile_image_sha[:16]}… 不一致；锚点属于**另一个构建**，禁止使用",
        )

    return {
        "ok": True,
        "step": "resolve-anchors",
        "imagePath": str(image_path),
        "imageSha256": image_sha,
        "imageBytes": len(data),
        "sizeOfImage": f"0x{size_image:x}",
        "profilePath": (profile_path if profile_path.is_absolute()
                        else REPO_ROOT / profile_path).as_posix(),
        "profileSha256": profile_sha,
        "allowRvaLiterals": bool(allow_rva_literals),
        "checks": [
            {
                "name": c.name,
                "rva": c.rva,
                "declaredHead32": c.declared_head32,
                "observedHead32": c.observed_head32,
                "mappedOffset": c.mapped_offset,
                "mappingCount": c.mapping_count,
                "head32Equal": c.declared_head32 == c.observed_head32,
            }
            for c in checks
        ],
        "anchors": {
            name: {
                "rva": f"0x{anchors[name].rva:x}",
                "provenance": anchors[name].provenance,
                "metadataFlags": list(anchors[name].metadata_flags),
                "guards": list(anchors[name].guards),
            }
            for name in require
        },
        "writesGameBytes": False,
        "memoryTouched": False,
    }


# ---------------------------------------------------------------------------
# C++ 翻译单元生成
# ---------------------------------------------------------------------------
#: 生成 TU 的结构常量。与 readback.py 的冻结副本必须一致，由 ``--selftest`` 比对。
CAPTURE_LAYOUT: dict[str, int] = {
    "kOwnerClassOffset": 0x00,
    "kOwnerSetOffset": 0x30,
    "kOwnerListOffset": 0x68,
    "kOwnerStateOffset": 0x9C,
    "kArrayHeaderPointerOffset": 0x00,
    "kArrayHeaderCountOffset": 0x18,
    "kArrayElementOffset": 0x20,
    "kListHeaderBytes": 0x20,
    "kSetHeaderBytes": 0x38,
    "kSetBucketsOffset": 0x10,
    "kSetSlotsOffset": 0x20,
    "kSetCountOffset": 0x28,
    "kSetLastIndexOffset": 0x2C,
    "kSetFreeHeadOffset": 0x30,
    "kWrapperBytes": 0x38,
    "kWrapperBackrefOffset": 0x20,
    "kWrapperConfigOffset": 0x28,
    "kWrapperEnabledOffset": 0x30,
    "kWrapperKindOffset": 0x34,
    "kConfigBackrefOffset": 0x18,
    "kConfigOwnerOffset": 0x20,
    "kMaxComponents": 256,
    "kSlotBytes": 12,
}
#: MWCAP 头部字段偏移（与 readback.py 的 CAPTURE_OFFSET_* 逐字节一致）。
#: 单独一张表，因为它们是**格式**常量而不是**结构**常量。
CAPTURE_HEADER_OFFSETS: dict[str, int] = {
    "kCaptureHeaderBytes": 28,
    "kCaptureOffsetVersion": 8,
    "kCaptureOffsetRecords": 12,
    "kCaptureOffsetOwner": 16,
    "kCaptureOffsetLayout": 24,
}


def _cpp_kind_table(allowed: Sequence[int]) -> str:
    rows = ",\n    ".join(
        f"{{{kind}, u\"{component_kind_name(kind)}\"}}" for kind in sorted(allowed)
    )
    return (
        "struct KindEntry { std::int32_t kind; const char16_t* name; };\n"
        "inline constexpr KindEntry kKindTable[] = { \\\n    "
        + rows
        + "};"
    )


def emit_native_tu(
    *,
    anchors: dict[str, Anchor],
    kinds: Sequence[int],
    run_ledger: dict[int, dict] | None = None,
) -> str:
    """生成**自足**的 C++ 翻译单元。只依赖 ``<cstdint>/<cstring>/<cstdio>`。"""
    ledger = dict(run_ledger if run_ledger is not None else KIND_RUN_LEDGER)
    attach = anchors["ATTACH"]
    layout = "\n".join(
        f"inline constexpr std::uint64_t {name} = 0x{value:X}ULL;" for name, value in CAPTURE_LAYOUT.items()
    )
    header_layout = "\n".join(
        f"inline constexpr std::uint64_t {name} = {value};"
        for name, value in CAPTURE_HEADER_OFFSETS.items()
    )
    return f'''// 由 {MODULE} 的 {TOOL}.py 生成（TOOL_VERSION={TOOL_VERSION}）。
// **自足**：只用 <cstdint>/<cstring>/<cstdio>，不 #include 工程内任何文件，
// 因此生成物可以在仓库之外编译与审计。
//
// ABI 依据（逐字）：
//   {SHARED_ABI_HEADER.as_posix()}:7
//     using AttachComponent = void* (__cdecl *)(void* owner, std::int32_t kind); // <rva>
// 锚点（构建绑定，**由调用方在编译前用磁盘镜像复核过**）：
//   ATTACH head32={attach.head32}
//          image_sha256={attach.image_sha256}
//   **本文件不含任何 RVA 字面量**（连注释里也没有）：锚点只以 head32 + imageSha256
//   记录，RVA 由宿主在运行期复核磁盘镜像后经 CombatMountContext 传入。
//   上一版把 rva 写进了这行注释，被本模块自己的「零硬编码地址」自检抓出来。
//   provenance: {SHARED_ABI_HEADER.as_posix()}:7 + native-options/runtime-profile.json
//               functions[head32 + imageSha256]
// 本文件**不含**任何硬编码地址常量：地址由宿主传入，宿主必须先过
// resolve_anchors() 的 sha256 + head32 复核（缺锚点即拒绝执行）。

#include <cstdint>
#include <cstring>
#include <cstdio>

// 本 TU 只用 C 运行时做**本地文件落盘**（MWCAP 转储与 manifest），不涉及 CRT 安全面。
// MSVC 在 /WX 下把 fopen 的 C4996 当错误，故就地点名抑制，而不是把 /WX 关掉 ——
// 关掉 /WX 会让所有其它警告失去闸门。
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4996)
#endif

namespace mt {{

{layout}

// MWCAP 头部偏移（显式；readback.py 用同一组数字，不许隐式对齐）。
{header_layout}

inline constexpr std::uint32_t kCaptureVersion = {CAPTURE_VERSION};
inline constexpr char kCaptureMagic[8] = {{'M','W','C','A','P','0','0','1'}};
inline constexpr const char* kCaptureLayoutId = "{CAPTURE_LAYOUT_ID}";

// kind 封闭表：由 46 项枚举生成（哨兵 47 已排除）。
// **完整声明**（不是裸初始化列表）：宏展开后必须自带类型与数组名，
// 否则 MSVC 会在初始化列表上直接报 C2059。
{_cpp_kind_table(kinds)}
inline constexpr std::size_t kKindCount = sizeof(kKindTable) / sizeof(kKindTable[0]);
inline constexpr bool kKindRunLedgerEmpty = {str(not ledger).lower()};

// ---------------------------------------------------------------------------
// 读层：每次读都同时喂给捕获器 ⇒ 转储**恰好等于**写入器读过的字节。
// ---------------------------------------------------------------------------
struct ReadSource {{
    bool (*read)(void* ctx, std::uint64_t address, void* target, std::size_t size);
    void* ctx;
}};

struct CaptureSink {{
    unsigned char* bytes;   // 宿主提供
    std::size_t capacity;
    std::size_t used;
    std::uint32_t records;
    bool overflow;
    void Append(std::uint64_t address, const void* data, std::size_t size) noexcept {{
        const std::size_t need = 8 + 4 + size;
        if (!bytes || used + need > capacity) {{ overflow = true; return; }}
        std::memcpy(bytes + used, &address, 8); used += 8;
        const std::uint32_t length = static_cast<std::uint32_t>(size);
        std::memcpy(bytes + used, &length, 4); used += 4;
        std::memcpy(bytes + used, data, size); used += size;
        ++records;
    }}
}};

struct Reader {{
    ReadSource source;
    CaptureSink* sink;
    bool Read(std::uint64_t address, void* target, std::size_t size) noexcept {{
        if (!size || size > (1u << 16) || !source.read) return false;
        if (!source.read(source.ctx, address, target, size)) return false;
        if (sink) sink->Append(address, target, size);
        return true;
    }}
    template <class T> bool At(std::uint64_t base, std::uint64_t offset, T& value) noexcept {{
        return Read(base + offset, &value, sizeof(value));
    }}
}};

inline bool Ptr(std::uint64_t value) noexcept {{
    return value >= 0x10000ULL && value < 0x0000800000000000ULL;
}}

template <class T> T From(const unsigned char* bytes, std::size_t offset) noexcept {{
    T value{{}}; std::memcpy(&value, bytes + offset, sizeof(value)); return value;
}}
struct ComponentRow {{
    std::uint64_t wrapper, wrapper_class, config, config_class;
    std::int32_t kind;
    std::uint8_t enabled;
    std::uint8_t reserved[3];
}};

enum class SnapshotCode : std::uint32_t {{
    okay, invalid_input, unreadable, invalid_structure, limit_exceeded,
    set_list_disagree, prefix_changed
}};

struct Snapshot {{
    SnapshotCode code;
    /// 具名失败点：``code`` 只说「哪一类」，这个字段说「哪一条检查」。
    const char* stage;
    std::uint64_t owner, owner_class, set, list;
    std::uint8_t owner_state;
    std::uint32_t set_count, list_count, set_capacity, list_capacity;
    std::int32_t set_last_index, set_free_head;
    std::uint32_t count;
    std::int32_t kinds[kMaxComponents];
    ComponentRow rows[kMaxComponents];
}};

/// 具名失败：同时设 code 与 stage。``code`` 只说「哪一类」检查失败，
/// ``stage`` 说「哪一条」—— 没有它，「invalid_structure」会把所有结构问题混成一句。
inline bool Fail(Snapshot& snapshot, SnapshotCode code, const char* stage) noexcept {{
    snapshot.code = code;
    snapshot.stage = stage;
    return false;
}}

// ---------------------------------------------------------------------------
// 结构遍历：SET 与 LIST **两套独立读**，两边 count 必须相等（否则 set_list_disagree）。
// ---------------------------------------------------------------------------
struct Workspace {{
    std::int32_t buckets[kMaxComponents];
    unsigned char slots[kMaxComponents * kSlotBytes];
    std::uint64_t items[kMaxComponents];
    bool seen[kMaxComponents];
}};

/// 诊断用的最后一帧：哪一条检查失败、当时看到的关键数值与**原始字节**。
struct FaultFrame {{
    const char* stage;
    std::uint32_t bucket;
    std::int32_t head;
    std::int32_t last_index;
    std::uint32_t capacity;
    std::uint32_t seen_count;
    std::int32_t first_bucket;
    std::uint64_t set_ptr;
    std::uint64_t buckets_ptr;
    std::uint64_t slots_ptr;
    std::uint64_t items_ptr;
    unsigned char set_header[kSetHeaderBytes];
}};
inline FaultFrame g_fault{{"-", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, {{0}}}};
/// 调用计数：用来回答「这段到底跑了没有」，不靠推断。
inline std::uint32_t g_snapshotOwnerCalls = 0;
inline std::uint32_t g_readStructuresCalls = 0;
inline std::uint32_t g_parseSetCalls = 0;

// 读层先读 SET 与 LIST 的**两套独立结构头**，再把槽位/桶/条目读进来。
// 每条失败都**具名**（``stage``），否则「invalid_structure」会掩盖真正的检查点。
inline bool ReadStructures(Reader& reader, Workspace& work, Snapshot& snapshot) noexcept {{
    ++g_readStructuresCalls;
    std::uint64_t buckets_ptr = 0, slots_ptr = 0, items_ptr = 0;
    g_fault.stage = "read_structures:enter";
    g_fault.set_ptr = snapshot.set;
    // 先把 SET 头的**原始字节**留一份：出问题时不必猜是哪一段读错了。
    if (!reader.Read(snapshot.set, g_fault.set_header, sizeof(g_fault.set_header)))
        return Fail(snapshot, SnapshotCode::unreadable, "set.header");
    if (!reader.At(snapshot.set, kSetBucketsOffset, buckets_ptr)) return Fail(snapshot, SnapshotCode::unreadable, "set.buckets_ptr");
    if (!reader.At(snapshot.set, kSetSlotsOffset, slots_ptr)) return Fail(snapshot, SnapshotCode::unreadable, "set.slots_ptr");
    if (!reader.At(snapshot.list, kSetBucketsOffset, items_ptr)) return Fail(snapshot, SnapshotCode::unreadable, "list.items_ptr");
    g_fault.buckets_ptr = buckets_ptr;
    g_fault.slots_ptr = slots_ptr;
    g_fault.items_ptr = items_ptr;
    std::int32_t set_count = 0, last_index = 0, list_count = 0;
    if (!reader.At(snapshot.set, kSetCountOffset, set_count)) return Fail(snapshot, SnapshotCode::unreadable, "set.count");
    if (!reader.At(snapshot.set, kSetLastIndexOffset, last_index)) return Fail(snapshot, SnapshotCode::unreadable, "set.last_index");
    if (!reader.At(snapshot.list, kArrayHeaderCountOffset, list_count)) return Fail(snapshot, SnapshotCode::unreadable, "list.count");
    if (!reader.At(snapshot.set, kSetFreeHeadOffset, snapshot.set_free_head)) return Fail(snapshot, SnapshotCode::unreadable, "set.free_head");
    if (set_count < 0 || last_index < 0 || set_count > last_index || list_count < 0)
        return Fail(snapshot, SnapshotCode::invalid_structure, "counts_negative_or_inverted");
    if (last_index > static_cast<std::int32_t>(kMaxComponents) ||
        list_count > static_cast<std::int32_t>(kMaxComponents))
        return Fail(snapshot, SnapshotCode::limit_exceeded, "counts_over_capacity");
    snapshot.set_count = static_cast<std::uint32_t>(set_count);
    snapshot.set_last_index = last_index;
    snapshot.list_count = static_cast<std::uint32_t>(list_count);

    // LIST 的 items 数组：容量与条目都必须真的落在捕获覆盖范围内。
    std::uint64_t item_capacity = 0;
    if (!Ptr(items_ptr)) return Fail(snapshot, SnapshotCode::invalid_structure, "list.items_not_a_pointer");
    if (!reader.At(items_ptr, kArrayHeaderCountOffset, item_capacity)) return Fail(snapshot, SnapshotCode::unreadable, "list.items_capacity");
    if (item_capacity > kMaxComponents) return Fail(snapshot, SnapshotCode::limit_exceeded, "list.capacity_over_limit");
    if (snapshot.list_count > item_capacity) return Fail(snapshot, SnapshotCode::invalid_structure, "list.count_over_capacity");
    snapshot.list_capacity = static_cast<std::uint32_t>(item_capacity);
    if (item_capacity && !reader.Read(items_ptr + kArrayElementOffset, work.items,
                                     static_cast<std::size_t>(item_capacity) * 8))
        return Fail(snapshot, SnapshotCode::unreadable, "list.items_array");

    // SET 的两种形状：
    //   (a) 空集合 —— buckets/slots 都是空指针，此时**必须** count=0、lastIndex=0、freeHead=-1；
    //   (b) 正常 —— 两者都是合法指针，容量相等，lastIndex <= 容量。
    if (!buckets_ptr && !slots_ptr) {{
        snapshot.set_capacity = 0;
        if (set_count != 0 || last_index != 0 || snapshot.set_free_head != -1)
            return Fail(snapshot, SnapshotCode::invalid_structure, "empty_set_shape");
        return true;
    }}
    if (!buckets_ptr || !slots_ptr)
        return Fail(snapshot, SnapshotCode::invalid_structure, "set.one_array_missing");
    if (!Ptr(buckets_ptr) || !Ptr(slots_ptr))
        return Fail(snapshot, SnapshotCode::invalid_structure, "set.arrays_not_pointers");
    std::uint64_t bucket_capacity = 0, slot_capacity = 0;
    if (!reader.At(buckets_ptr, kArrayHeaderCountOffset, bucket_capacity)) return Fail(snapshot, SnapshotCode::unreadable, "set.buckets_capacity");
    if (!reader.At(slots_ptr, kArrayHeaderCountOffset, slot_capacity)) return Fail(snapshot, SnapshotCode::unreadable, "set.slots_capacity");
    if (bucket_capacity > kMaxComponents || slot_capacity > kMaxComponents)
        return Fail(snapshot, SnapshotCode::limit_exceeded, "set.capacity_over_limit");
    if (!bucket_capacity || bucket_capacity != slot_capacity)
        return Fail(snapshot, SnapshotCode::invalid_structure, "set.capacity_mismatch");
    if (last_index > static_cast<std::int32_t>(slot_capacity))
        return Fail(snapshot, SnapshotCode::invalid_structure, "set.last_index_over_capacity");
    snapshot.set_capacity = static_cast<std::uint32_t>(bucket_capacity);
    if (!reader.Read(buckets_ptr + kArrayElementOffset, work.buckets,
                     static_cast<std::size_t>(bucket_capacity) * sizeof(work.buckets[0])))
        return Fail(snapshot, SnapshotCode::unreadable, "set.buckets_array");
    if (!reader.Read(slots_ptr + kArrayElementOffset, work.slots,
                     static_cast<std::size_t>(slot_capacity) * kSlotBytes))
        return Fail(snapshot, SnapshotCode::unreadable, "set.slots_array");
    return true;
}}

inline bool ReadRow(Reader& reader, const Snapshot& snapshot, std::uint64_t pointer,
                    ComponentRow& row) noexcept {{
    unsigned char wrapper[kWrapperBytes]{{}}, config[kSetHeaderBytes]{{}};
    if (!Ptr(pointer)) return false;
    if (!reader.Read(pointer, wrapper, sizeof(wrapper))) return false;
    row.wrapper = pointer;
    row.wrapper_class = From<std::uint64_t>(wrapper, 0);
    row.config = From<std::uint64_t>(wrapper, kWrapperConfigOffset);
    row.kind = From<std::int32_t>(wrapper, kWrapperKindOffset);
    row.enabled = wrapper[kWrapperEnabledOffset];
    if (!Ptr(row.wrapper_class) || !Ptr(row.config) || row.kind <= 0) return false;
    if (From<std::uint64_t>(wrapper, kWrapperBackrefOffset) != snapshot.owner) return false;
    if (!reader.Read(row.config, config, sizeof(config))) return false;
    row.config_class = From<std::uint64_t>(config, 0);
    return Ptr(row.config_class) && From<std::uint64_t>(config, kConfigBackrefOffset) == pointer &&
           From<std::uint64_t>(config, kConfigOwnerOffset) == snapshot.owner;
}}

inline bool ParseSet(Workspace& work, Snapshot& snapshot) noexcept {{
    ++g_parseSetCalls;
    g_fault.stage = "parse_set:enter";
    g_fault.last_index = snapshot.set_last_index;
    g_fault.capacity = snapshot.set_capacity;
    g_fault.first_bucket = snapshot.set_capacity ? work.buckets[0] : 0;
    std::uint32_t seen_count = 0;
    for (std::uint32_t bucket = 0; bucket < snapshot.set_capacity; ++bucket) {{
        const std::int32_t head = work.buckets[bucket];
        // **-1 是「空桶」的哨兵**，不是非法值：合法范围是 -1 或 [1, lastIndex]。
        // 这里曾经写成 ``head < 0`` ⇒ 任何空桶都判非法，导致「第一次挂载前」
        // 快照直接失败（共享件 component_attachment.cpp:94 用 ``head < 0`` 是对的，
        // 因为它那里的 head 已经先 ``-1`` 过；本地这份没有）。
        if (head < -1 || head > snapshot.set_last_index) {{
            g_fault.stage = "bucket_head_out_of_range";
            g_fault.bucket = bucket;
            g_fault.head = head;
            return Fail(snapshot, SnapshotCode::invalid_structure, "bucket_head_out_of_range");
        }}
        if (head == -1) continue;        for (std::int32_t index = head - 1; index != -1;) {{
            if (index < 0 || index >= snapshot.set_last_index || work.seen[index])
                return Fail(snapshot, SnapshotCode::invalid_structure, "slot_chain_index_bad");
            work.seen[index] = true;
            const unsigned char* slot = work.slots + static_cast<std::size_t>(index) * kSlotBytes;
            const std::int32_t hash = From<std::int32_t>(slot, 0);
            const std::int32_t next = From<std::int32_t>(slot, 4);
            const std::int32_t value = From<std::int32_t>(slot, 8);
            if (hash < 0 || static_cast<std::uint32_t>(hash) % snapshot.set_capacity != bucket)
                return Fail(snapshot, SnapshotCode::invalid_structure, "slot_hash_not_in_bucket");
            if (value <= 0)
                return Fail(snapshot, SnapshotCode::invalid_structure, "slot_value_not_positive");
            for (std::uint32_t i = 0; i < seen_count; ++i) {{
                if (snapshot.kinds[i] == value)
                    return Fail(snapshot, SnapshotCode::invalid_structure, "duplicate_kind_in_set");
            }}
            snapshot.kinds[seen_count++] = value;
            index = next;
        }}
    }}
    if (seen_count != snapshot.set_count)
        return Fail(snapshot, SnapshotCode::invalid_structure, "set_walk_count_mismatch");
    std::int32_t free_head = snapshot.set_free_head;
    for (std::uint32_t i = snapshot.set_count;
         i < static_cast<std::uint32_t>(snapshot.set_last_index); ++i) {{
        if (free_head < 0 || free_head >= snapshot.set_last_index || work.seen[free_head]) {{
            std::printf("free_list_fault i=%u free_head=%d last=%d seen=%d n0=%d n1=%d n63=%d\\n",
                        i, free_head, snapshot.set_last_index,
                        (free_head >= 0 && free_head < static_cast<std::int32_t>(kMaxComponents))
                            ? static_cast<int>(work.seen[free_head]) : -1,
                        From<std::int32_t>(work.slots + 0 * kSlotBytes, 4),
                        From<std::int32_t>(work.slots + 1 * kSlotBytes, 4),
                        From<std::int32_t>(work.slots + 63 * kSlotBytes, 4));
            return Fail(snapshot, SnapshotCode::invalid_structure, "free_list_bad_link");
        }}
        work.seen[free_head] = true;
        free_head = From<std::int32_t>(
            work.slots + static_cast<std::size_t>(free_head) * kSlotBytes, 4);
    }}
    if (free_head != -1)
        return Fail(snapshot, SnapshotCode::invalid_structure, "free_list_unterminated");
    for (std::uint32_t i = 0; i < static_cast<std::uint32_t>(snapshot.set_last_index); ++i) {{
        if (!work.seen[i])
            return Fail(snapshot, SnapshotCode::invalid_structure, "slot_neither_used_nor_free");
    }}
    return true;
}}

inline void SnapshotOwner(Reader& reader, std::uint64_t owner, Workspace& work,
                          Snapshot& snapshot) noexcept {{
    ++g_snapshotOwnerCalls;
    std::memset(&snapshot, 0, sizeof(snapshot));
    snapshot.code = SnapshotCode::invalid_input;
    snapshot.stage = "start";
    snapshot.owner = owner;
    if (!Ptr(owner)) {{ snapshot.stage = "owner_not_a_pointer"; return; }}
    if (!reader.At(owner, kOwnerClassOffset, snapshot.owner_class)) {{ snapshot.stage = "owner.class"; return; }}
    if (!reader.At(owner, kOwnerSetOffset, snapshot.set)) {{ snapshot.stage = "owner.set"; return; }}
    if (!reader.At(owner, kOwnerListOffset, snapshot.list)) {{ snapshot.stage = "owner.list"; return; }}
    if (!reader.At(owner, kOwnerStateOffset, snapshot.owner_state)) {{ snapshot.stage = "owner.state"; return; }}
    if (!Ptr(snapshot.owner_class)) {{ snapshot.stage = "owner.class_not_pointer"; return; }}
    if (!Ptr(snapshot.set) || !Ptr(snapshot.list)) {{ snapshot.stage = "owner.set_or_list_not_pointer"; return; }}
    if (snapshot.set == snapshot.list) {{ snapshot.stage = "owner.set_list_alias"; return; }}
    std::memset(&work, 0, sizeof(work));
    if (!ReadStructures(reader, work, snapshot)) return;
    if (!ParseSet(work, snapshot)) return;
    for (std::uint32_t i = 0; i < snapshot.list_count; ++i) {{
        if (!ReadRow(reader, snapshot, work.items[i], snapshot.rows[i])) {{
            snapshot.code = SnapshotCode::invalid_structure;
            snapshot.stage = "list_row_unreadable_or_identity_failed";
            return;
        }}
        for (std::uint32_t j = 0; j < i; ++j) {{
            if (snapshot.rows[i].kind == snapshot.rows[j].kind)
                return static_cast<void>(Fail(snapshot, SnapshotCode::invalid_structure, "list_duplicate_kind"));
            if (snapshot.rows[i].wrapper == snapshot.rows[j].wrapper)
                return static_cast<void>(Fail(snapshot, SnapshotCode::invalid_structure, "list_duplicate_wrapper"));
            if (snapshot.rows[i].config == snapshot.rows[j].config)
                return static_cast<void>(Fail(snapshot, SnapshotCode::invalid_structure, "list_duplicate_config"));
        }}
    }}
    if (snapshot.list_count != snapshot.set_count)
        return static_cast<void>(Fail(snapshot, SnapshotCode::set_list_disagree, "set_list_count_disagree"));
    for (std::uint32_t i = 0; i < snapshot.list_count; ++i) {{
        bool found = false;
        for (std::uint32_t j = 0; j < snapshot.set_count; ++j) {{
            if (snapshot.rows[i].kind == snapshot.kinds[j]) found = true;
        }}
        if (!found)
            return static_cast<void>(Fail(snapshot, SnapshotCode::set_list_disagree, "list_kind_absent_from_set"));
    }}
    snapshot.count = snapshot.list_count;
    snapshot.code = SnapshotCode::okay;
    snapshot.stage = "okay";
}}

// 前缀必须逐行逐字段不变：一次只允许**追加**，不允许改动既有行。
inline bool PrefixUnchanged(const Snapshot& before, const Snapshot& after) noexcept {{
    if (after.count != before.count + 1 || after.set_count != before.set_count + 1) return false;
    for (std::uint32_t i = 0; i < before.count; ++i) {{
        if (std::memcmp(&before.rows[i], &after.rows[i], sizeof(ComponentRow))) return false;
    }}
    return true;
}}

// ---------------------------------------------------------------------------
// 写入器
// ---------------------------------------------------------------------------
using AttachComponent = void* (__cdecl*)(void* owner, std::int32_t kind);

enum class MountCode : std::uint32_t {{
    attached_verified, existing, invalid_input, unknown_kind, before_failed,
    identity_mismatch, missing_binding, null_return, prefix_changed,
    after_failed, context_changed, call_exception, capture_limit
}};

struct MountEvidence {{
    std::uint64_t owner, owner_class, wrapper_class, config_class;
    std::int32_t kind;
    bool owner_and_thread_verified;
}};

struct MountRequest {{
    std::uint64_t owner;
    std::int32_t kind;
    MountEvidence evidence;
}};

struct MountResult {{
    MountCode code;
    ComponentRow component;
    std::uint64_t returned_wrapper;
    bool attach_called, before_verified, after_verified;
    Snapshot before, after;
    /// 本次挂载**自己的**捕获接收器（调用方传入的那个）。它只含这次挂载读过的字节。
    CaptureSink* sink;
    /// after 侧单独的接收器（可空）。非空时 after 快照只写这里。
    CaptureSink* after_sink;
}};

inline bool KnownKind(std::int32_t kind) noexcept {{
    for (std::size_t i = 0; i < kKindCount; ++i) if (kKindTable[i].kind == kind) return true;
    return false;
}}

/// 只调用一次 attach，前后各做一次全量读回；**任何一步失败都不算成功**。
/// ``sink`` 收 before 侧读数，``afterSink``（可空）收 after 侧读数 —— 分开是为了让
/// 独立读回能拿**两份互不重叠的字节**去自己重算「追加」这件事（同一份字节里
/// 既读 before 又读 after 会让同一地址出现两个值，正是 capture_region_unstable）。
inline void MountOne(ReadSource source, AttachComponent attach, const MountRequest& request,
                     Workspace& workspace, CaptureSink* sink, MountResult& result,
                     CaptureSink* afterSink = nullptr) noexcept {{
    std::memset(&result, 0, sizeof(result));
    result.sink = sink;
    result.after_sink = afterSink;
    result.code = MountCode::invalid_input;
    if (!Ptr(request.owner) || !request.evidence.owner_and_thread_verified) return;
    if (!KnownKind(request.kind)) {{ result.code = MountCode::unknown_kind; return; }}
    const MountEvidence& evidence = request.evidence;
    if (evidence.kind != request.kind || !Ptr(evidence.owner_class) ||
        !Ptr(evidence.wrapper_class) || !Ptr(evidence.config_class)) return;
    Reader reader{{source, sink}};
    SnapshotOwner(reader, request.owner, workspace, result.before);
    result.code = MountCode::before_failed;
    if (result.before.code != SnapshotCode::okay) return;
    result.before_verified = true;
    result.code = MountCode::identity_mismatch;
    if (result.before.owner_class != evidence.owner_class) return;
    for (std::uint32_t i = 0; i < result.before.count; ++i) {{
        const ComponentRow& row = result.before.rows[i];
        if (row.kind != request.kind) continue;
        if (row.wrapper_class != evidence.wrapper_class || row.config_class != evidence.config_class) return;        result.component = row; result.code = MountCode::existing; return;
    }}
    result.code = MountCode::capture_limit;
    if (result.before.count == kMaxComponents) return;
    // **missing_binding 必须在其它前置之后**：否则「没给函数指针」会被更早的
    // invalid_input 掩掉，调用方拿到的就不是那条真正的原因（实测踩过）。
    result.code = MountCode::missing_binding;
    if (!attach) return;
    result.attach_called = true;
    Reader afterReader{{source, afterSink ? afterSink : sink}};
    try {{
        result.returned_wrapper =
            reinterpret_cast<std::uint64_t>(attach(reinterpret_cast<void*>(request.owner), request.kind));
    }} catch (...) {{
        result.code = MountCode::call_exception;
        SnapshotOwner(afterReader, request.owner, workspace, result.after);
        result.after_verified = result.after.code == SnapshotCode::okay;
        return;
    }}
    SnapshotOwner(afterReader, request.owner, workspace, result.after);
    result.code = MountCode::after_failed;
    if (result.after.code != SnapshotCode::okay) return;
    result.after_verified = true;
    result.code = MountCode::context_changed;
    if (result.before.owner_class != result.after.owner_class ||
        result.before.set != result.after.set || result.before.list != result.after.list ||
        result.before.owner_state != result.after.owner_state) return;
    result.code = MountCode::null_return;
    if (!result.returned_wrapper) return;
    result.code = MountCode::prefix_changed;
    if (!PrefixUnchanged(result.before, result.after)) return;
    const ComponentRow& added = result.after.rows[result.before.count];
    if (added.kind != request.kind || added.wrapper_class != evidence.wrapper_class ||
        added.config_class != evidence.config_class || added.wrapper != result.returned_wrapper) return;
    result.component = added;
    result.code = MountCode::attached_verified;
}}

inline const char* SnapshotCodeName(SnapshotCode code) noexcept {{
    switch (code) {{
        case SnapshotCode::okay: return "okay";
        case SnapshotCode::invalid_input: return "invalid_input";
        case SnapshotCode::unreadable: return "unreadable";
        case SnapshotCode::invalid_structure: return "invalid_structure";
        case SnapshotCode::limit_exceeded: return "limit_exceeded";
        case SnapshotCode::set_list_disagree: return "set_list_disagree";
        case SnapshotCode::prefix_changed: return "prefix_changed";
    }}
    return "unknown";
}}

inline const char* MountCodeName(MountCode code) noexcept {{
    switch (code) {{
        case MountCode::attached_verified: return "attached_verified";
        case MountCode::existing: return "existing";
        case MountCode::invalid_input: return "invalid_input";
        case MountCode::unknown_kind: return "unknown_kind";
        case MountCode::before_failed: return "before_failed";
        case MountCode::identity_mismatch: return "identity_mismatch";
        case MountCode::missing_binding: return "missing_binding";
        case MountCode::null_return: return "null_return";
        case MountCode::prefix_changed: return "prefix_changed";
        case MountCode::after_failed: return "after_failed";
        case MountCode::context_changed: return "context_changed";
        case MountCode::call_exception: return "call_exception";
        case MountCode::capture_limit: return "capture_limit";
    }}
    return "unknown";
}}

// ---------------------------------------------------------------------------
// **固定入口**（不是每次现写）：宿主进程只需要这一个函数 + 一个捕获接收器。
// 地址与 kind 都由宿主提供；本函数自己不含任何地址常量。
// ---------------------------------------------------------------------------
struct MountInput {{
    std::uint64_t owner, owner_class, wrapper_class, config_class;
    std::int32_t kind;
    bool owner_and_thread_verified;
}};

/// 返回 MountCode 的数值；若 sink 非空，本函数读过的每个字节都被记进 sink。
inline std::uint32_t MountComponentEntry(ReadSource source, AttachComponent attach,
                                         const MountInput& input, CaptureSink* sink) noexcept {{
    // MountEvidence 的字段顺序 = (owner, owner_class, wrapper_class, config_class, kind, flag)。
    const MountEvidence evidence{{input.owner, input.owner_class, input.wrapper_class,
                                  input.config_class, input.kind,
                                  input.owner_and_thread_verified}};
    const MountRequest request{{input.owner, input.kind, evidence}};
    static thread_local Workspace workspace;
    MountResult result;
    MountOne(source, attach, request, workspace, sink, result);
    return static_cast<std::uint32_t>(result.code);
}}

// ---------------------------------------------------------------------------
// 布局探针（**编译器的答案**，不是本文件手抄的数字）
// ---------------------------------------------------------------------------
/// 唯一的手抄事实：MWCAP 头部偏移与格式版本。其余全部由 sizeof/offsetof 推导。
struct LayoutProbe {{
    std::uint32_t captureVersion;
    std::uint64_t captureHeaderBytes, offsetVersion, offsetRecords, offsetOwner, offsetLayout;
    std::uint64_t recordHeaderBytes, magicBytes;
    std::uint64_t wrapperBytes, setHeaderBytes, listHeaderBytes, slotBytes;
    std::uint64_t ownerSetOffset, ownerListOffset, ownerStateOffset;
    std::uint64_t arrayCountOffset, arrayElementOffset;
    std::uint64_t wrapperKindOffset, wrapperConfigOffset, wrapperEnabledOffset, wrapperBackrefOffset;
    std::uint64_t configBackrefOffset, configOwnerOffset;
    std::uint64_t setBucketsOffset, setSlotsOffset, setCountOffset, setLastIndexOffset, setFreeHeadOffset;
    std::uint64_t maxComponents, kindCount;
    std::uint64_t componentRowBytes, mountResultBytes, snapshotBytes, captureSinkBytes;
    bool kindRunLedgerEmpty;
}};

inline LayoutProbe MakeLayoutProbe() noexcept {{
    LayoutProbe probe{{}};
    probe.captureVersion = kCaptureVersion;
    probe.captureHeaderBytes = kCaptureHeaderBytes;
    probe.offsetVersion = kCaptureOffsetVersion;
    probe.offsetRecords = kCaptureOffsetRecords;
    probe.offsetOwner = kCaptureOffsetOwner;
    probe.offsetLayout = kCaptureOffsetLayout;
    probe.recordHeaderBytes = 12;
    probe.magicBytes = sizeof(kCaptureMagic);
    probe.wrapperBytes = kWrapperBytes;
    probe.setHeaderBytes = kSetHeaderBytes;
    probe.listHeaderBytes = kListHeaderBytes;
    probe.slotBytes = kSlotBytes;
    probe.ownerSetOffset = kOwnerSetOffset;
    probe.ownerListOffset = kOwnerListOffset;
    probe.ownerStateOffset = kOwnerStateOffset;
    probe.arrayCountOffset = kArrayHeaderCountOffset;
    probe.arrayElementOffset = kArrayElementOffset;
    probe.wrapperKindOffset = kWrapperKindOffset;
    probe.wrapperConfigOffset = kWrapperConfigOffset;
    probe.wrapperEnabledOffset = kWrapperEnabledOffset;
    probe.wrapperBackrefOffset = kWrapperBackrefOffset;
    probe.configBackrefOffset = kConfigBackrefOffset;
    probe.configOwnerOffset = kConfigOwnerOffset;
    probe.setBucketsOffset = kSetBucketsOffset;
    probe.setSlotsOffset = kSetSlotsOffset;
    probe.setCountOffset = kSetCountOffset;
    probe.setLastIndexOffset = kSetLastIndexOffset;
    probe.setFreeHeadOffset = kSetFreeHeadOffset;
    probe.maxComponents = kMaxComponents;
    probe.kindCount = kKindCount;
    probe.componentRowBytes = sizeof(ComponentRow);
    probe.mountResultBytes = sizeof(MountResult);
    probe.snapshotBytes = sizeof(Snapshot);
    probe.captureSinkBytes = sizeof(CaptureSink);
    probe.kindRunLedgerEmpty = kKindRunLedgerEmpty;
    return probe;
}}

// ---------------------------------------------------------------------------
// 捕获落盘：MWCAP 原始转储 —— **恰好**是写入器读过的字节。
// 宿主给出 sink.bytes/容量；本函数把它编码成 readback.py 能独立解析的格式。
// ---------------------------------------------------------------------------
inline std::size_t EncodeCapture(unsigned char* out, std::size_t out_capacity,
                                 const CaptureSink& sink, std::uint64_t owner) noexcept {{
    const std::size_t need = kCaptureHeaderBytes + sink.used;
    if (!out || need > out_capacity) return 0;
    std::memcpy(out, kCaptureMagic, 8);
    // **显式偏移**，不用隐式对齐的 struct：C++ 与 Python 两头必须逐字节一致。
    // 第一版在 Python 侧按 24 字节读头，而这里写的是 28 字节 ⇒ 读回把记录地址
    // 当成了版本号。偏移写出来才有唯一解释。
    std::memcpy(out + kCaptureOffsetVersion, &kCaptureVersion, 4);
    const std::uint32_t record_count = sink.records;
    std::memcpy(out + kCaptureOffsetRecords, &record_count, 4);
    std::memcpy(out + kCaptureOffsetOwner, &owner, 8);
    const std::uint32_t layout_id = 1u;
    std::memcpy(out + kCaptureOffsetLayout, &layout_id, 4);
    std::memcpy(out + kCaptureHeaderBytes, sink.bytes, sink.used);
    return need;
}}

}}  // namespace mt

#ifdef _MSC_VER
#pragma warning(pop)
#endif
'''


# ---------------------------------------------------------------------------
# 驱动生成（把生成物真的跑起来）
# ---------------------------------------------------------------------------
def emit_driver_tu(*, kinds: Sequence[int]) -> str:
    """生成驱动：自建桩内存 + 真实函数指针 + 断言 + MWCAP 落盘。

    驱动**包含**生成 TU，因此它验的是**生成物本身**，不是另写一份逻辑。

    **所有 kind 都从本次声明的 kinds 里取**（不再有默认的 extra/sixth 常量）：
    旧版让 `kKindExtra` 默认取 46、`kKindSixth` 默认取 24，于是用
    `--kinds 17,19,24,26,33` 时 mount9 会拿到**不在集合里**的 46 ⇒ 驱动在
    运行期返回 unknown_kind 而失败（实测踩到）。现在不足 5 个就在 prepare 期具名拒绝。
    """
    ordered = sorted({int(k) for k in kinds})
    if len(ordered) < 5:
        raise MounterError(
            "DRIVER_NEEDS_FIVE_KINDS",
            f"驱动需要至少 5 个 kind（主挂载 / 第二个 / 拒绝用例 / 前缀用例 / 可重算对），"
            f"得到 {len(ordered)} 个：{ordered}；用 --kinds 收窄时请至少给 5 个",
        )
    k0, k1, k2, k3, k4 = ordered[:5]
    k_first, k_second, k_fourth, k_extra, k_sixth = k0, k1, k2, k3, k4
    return f'''// 由 {MODULE} 的 {TOOL}.py --driver 生成。包含生成 TU 并真的调用它。
// 桩内存是进程内自建数组（真实可写内存），**不是**游戏进程、**不是**游戏写入。
#include "component_mounter_native.cpp"

#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

// 驱动落盘 MWCAP，同样只用 C 运行时。
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4996)
#endif

namespace {{

constexpr std::uint64_t kBase = 0x0000000140000000ULL;
constexpr std::size_t kStride = 0x1000;
constexpr std::size_t kSlots = 64;
/// 保留区大小：桩地址必须真的可写。第一版用 std::vector 当桩，
/// 却按**绝对地址** memcpy ⇒ 直接 AV（0xC0000005）。
constexpr std::size_t kRegionBytes = kStride * 64;

// 本次驱动使用的三个 kind（由 Python 侧注入，避免任何运行时插值）。
// 本次驱动使用的 kinds（**全部从 --kinds 声明集里取**，见 Python 侧注释）。
constexpr std::int32_t kKindFirst = {k_first};
constexpr std::int32_t kKindSecond = {k_second};
constexpr std::int32_t kKindFourth = {k_fourth};
/// 「前缀被改」用例用的 kind。
constexpr std::int32_t kKindExtra = {k_extra};
/// 「可独立重算的追加对」用的 kind。
constexpr std::int32_t kKindSixth = {k_sixth};

void* g_region = nullptr;

/// 只在保留区内读；越界返回 false。
bool StubRead(void* /*ctx*/, std::uint64_t address, void* target, std::size_t size) noexcept {{
    if (!g_region || address < kBase || size == 0) return false;
    const std::size_t offset = static_cast<std::size_t>(address - kBase);
    if (offset + size > kRegionBytes) return false;
    std::memcpy(target, static_cast<unsigned char*>(g_region) + offset, size);
    return true;
}}

void Put(std::uint64_t address, const void* value, std::size_t size) noexcept {{
    std::memcpy(static_cast<unsigned char*>(g_region) + (address - kBase), value, size);
}}
template <class T> void PutU(std::uint64_t address, T value) noexcept {{ Put(address, &value, sizeof(T)); }}

// 桩内存里的固定地址（都在 kBase 之上，绝不与真实进程有关）。
constexpr std::uint64_t kOwnerAddress = kBase + 0x000;
constexpr std::uint64_t kSetAddress = kBase + kStride * 1;
constexpr std::uint64_t kListAddress = kBase + kStride * 2;
constexpr std::uint64_t kBucketsAddress = kBase + kStride * 3;
constexpr std::uint64_t kSlotsAddress = kBase + kStride * 4;
constexpr std::uint64_t kItemsAddress = kBase + kStride * 5;
constexpr std::uint64_t kRowBase = kBase + kStride * 6;
constexpr std::uint64_t kConfigBase = kBase + kStride * 7;
constexpr std::uint64_t kClassAddress = kBase + kStride * 8;

std::int32_t g_attachedCount = 0;
std::int32_t g_attachCalls = 0;
std::int32_t g_ownerMismatch = 0;
bool g_attachThrows = false;
bool g_attachReturnsNull = false;
/// 为「前缀被改」用例而设：置位时 attach 会在**自己的调用里**改掉第 0 行的一个字节。
/// 必须在调用里改 —— 在调用前后改，改的是同一份内存，before 与 after 会看到同一个值，
/// PrefixUnchanged 自然照样为真（这正是第一版前缀用例「通过」了追加的原因）。
bool g_corruptPrefixOnAttach = false;

void* __cdecl AttachHook(void* owner, std::int32_t kind) noexcept(false) {{
    // owner 必须就是桩实体本身：桩式 attach 只在这个实体上追加行。
    if (reinterpret_cast<std::uint64_t>(owner) != kOwnerAddress) {{ ++g_ownerMismatch; return nullptr; }}
    ++g_attachCalls;
    if (g_attachThrows) throw 7;
    if (g_attachReturnsNull) return nullptr;
    // 按真实语义把新行**追加**进 LIST 与 SET，并回填回指。
    const std::uint32_t index = static_cast<std::uint32_t>(g_attachedCount);
    const std::uint64_t row = kRowBase + index * kStride;
    const std::uint64_t config = kConfigBase + index * kStride;
    PutU<std::uint64_t>(row, kClassAddress);                                  // wrapper_class
    PutU<std::uint64_t>(row + mt::kWrapperConfigOffset, config);              // config
    PutU<std::int32_t>(row + mt::kWrapperKindOffset, kind);                   // kind
    PutU<std::uint64_t>(row + mt::kWrapperBackrefOffset, kOwnerAddress);      // owner 回指
    PutU<unsigned char>(row + mt::kWrapperEnabledOffset, 1);                  // enabled
    PutU<std::uint64_t>(config, kClassAddress);                               // config_class
    PutU<std::uint64_t>(config + mt::kConfigBackrefOffset, row);              // 回指 wrapper
    PutU<std::uint64_t>(config + mt::kConfigOwnerOffset, kOwnerAddress);      // 回指 owner

    // LIST：把新行地址写进 items[index]，并抬高 LIST 与 items 数组的 count。
    PutU<std::uint64_t>(
        kItemsAddress + mt::kArrayElementOffset + index * 8, row);
    PutU<std::int32_t>(kListAddress + mt::kArrayHeaderCountOffset,
                       static_cast<std::int32_t>(index + 1));
    PutU<std::int32_t>(kItemsAddress + mt::kArrayHeaderCountOffset,
                       static_cast<std::int32_t>(index + 1));

    // SET：占一个 slot（hash/next/value），把桶指向它，并抬高 SET 的 count。
    const std::uint64_t slot = kSlotsAddress + mt::kArrayElementOffset + index * mt::kSlotBytes;
    const std::int32_t bucket = kind % static_cast<std::int32_t>(kSlots);
    PutU<std::int32_t>(slot, bucket);        // hash 必须满足 hash % capacity == bucket
    PutU<std::int32_t>(slot + 4, -1);        // next = 链尾
    PutU<std::int32_t>(slot + 8, kind);      // value = kind
    PutU<std::int32_t>(kBucketsAddress + mt::kArrayElementOffset + bucket * 4, index + 1);
    PutU<std::int32_t>(kSetAddress + mt::kSetCountOffset, static_cast<std::int32_t>(index + 1));
    PutU<std::int32_t>(kBucketsAddress + mt::kArrayHeaderCountOffset, static_cast<std::int32_t>(kSlots));
    PutU<std::int32_t>(kSlotsAddress + mt::kArrayHeaderCountOffset, static_cast<std::int32_t>(kSlots));
    PutU<std::int32_t>(kSetAddress + mt::kSetLastIndexOffset, static_cast<std::int32_t>(kSlots));
    // 占掉一个空闲槽 ⇒ 空闲链表要**前进一步**：freeHead 必须重新指向下一个未用槽。
    // 漏了这一步，after 快照的 free-list 走链会撞上刚被占用的槽（free_list_bad_link）。
    PutU<std::int32_t>(kSetAddress + mt::kSetFreeHeadOffset,
                       (index + 1 < static_cast<std::uint32_t>(kSlots))
                           ? static_cast<std::int32_t>(index + 1) : -1);
    if (g_corruptPrefixOnAttach && index > 0) {{
        // 改动**既有行**的一个字节：让 before/after 的前缀真的不同。
        const auto* regionBytes = static_cast<const unsigned char*>(g_region);
        const std::uint64_t row0 = mt::From<std::uint64_t>(
            regionBytes + (kItemsAddress + mt::kArrayElementOffset - kBase), 0);
        PutU<unsigned char>(row0 + mt::kWrapperEnabledOffset, 200);
    }}
    g_attachedCount = static_cast<std::int32_t>(index + 1);
    return reinterpret_cast<void*>(row);
}}

int g_failures = 0;
void Check(bool condition, const char* label) {{
    if (!condition) {{ ++g_failures; std::printf("FAIL %s\\n", label); }}
    else std::printf("ok   %s\\n", label);
}}
/// 带实参的检查：失败时把**真实**取值打出来，便于定位（而不是只说「不是它」）。
template <class A>
void CheckEq(const char* label, A observed, A expected) {{
    if (observed == expected) {{ std::printf("ok   %s\\n", label); return; }}
    ++g_failures;
    std::printf("FAIL %s observed=%lld expected=%lld\\n", label,
                static_cast<long long>(observed), static_cast<long long>(expected));
}}

/// 驱动侧的挂载包装：把每次挂载的入参与结果打出来。
/// **放在驱动里而不是生成物里**：生成 TU 要能在真实宿主里静止使用，不该刷日志。
void RunMount(const char* label, mt::ReadSource source, mt::AttachComponent attach,
              const mt::MountRequest& request, mt::Workspace& workspace,
              mt::CaptureSink* sink, mt::MountResult& result) {{
    mt::MountOne(source, attach, request, workspace, sink, result);
    std::printf("trace %-26s reqKind=%-5d code=%-18s before=%u after=%u attachCalled=%d calls=%d\\n",
                label, request.kind, mt::MountCodeName(result.code), result.before.count,
                result.after.count, result.attach_called ? 1 : 0, g_attachCalls);
}}

/// before/after 分开收的变体（给独立读回的重算用）。
void RunMountPair(const char* label, mt::ReadSource source, mt::AttachComponent attach,
                  const mt::MountRequest& request, mt::Workspace& workspace,
                  mt::CaptureSink* beforeSink, mt::CaptureSink* afterSink,
                  mt::MountResult& result) {{
    mt::MountOne(source, attach, request, workspace, beforeSink, result, afterSink);
    std::printf("trace %-26s reqKind=%-5d code=%-18s before=%u after=%u attachCalled=%d "
                "beforeRecords=%u afterRecords=%u\\n",
                label, request.kind, mt::MountCodeName(result.code), result.before.count,
                result.after.count, result.attach_called ? 1 : 0,
                beforeSink ? beforeSink->records : 0, afterSink ? afterSink->records : 0);
}}

std::size_t CaptureBytes = 0;

const char* g_outputDirectory = nullptr;

// 标准 SHA-256（FIPS 180-4）。写进 manifest，让读回能核对「声明的就是这份字节」。
struct Sha256 {{
    std::uint32_t state[8];
    std::uint64_t length;
    unsigned char block[64];
    std::size_t fill;
    void Init() noexcept {{
        static const std::uint32_t init[8] = {{0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                                               0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u}};
        for (int i = 0; i < 8; ++i) state[i] = init[i];
        length = 0; fill = 0;
        std::memset(block, 0, sizeof(block));
    }}
    static std::uint32_t Rotr(std::uint32_t x, std::uint32_t n) noexcept {{ return (x >> n) | (x << (32 - n)); }}
    void Compress(const unsigned char* chunk) noexcept {{
        static const std::uint32_t k[64] = {{
            0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
            0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
            0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
            0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
            0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
            0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
            0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
            0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u}};
        std::uint32_t w[64];
        for (int i = 0; i < 16; ++i)
            w[i] = (static_cast<std::uint32_t>(chunk[i*4]) << 24) |
                   (static_cast<std::uint32_t>(chunk[i*4+1]) << 16) |
                   (static_cast<std::uint32_t>(chunk[i*4+2]) << 8) |
                   static_cast<std::uint32_t>(chunk[i*4+3]);
        for (int i = 16; i < 64; ++i) {{
            const std::uint32_t s0 = Rotr(w[i-15],7) ^ Rotr(w[i-15],18) ^ (w[i-15] >> 3);
            const std::uint32_t s1 = Rotr(w[i-2],17) ^ Rotr(w[i-2],19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }}
        std::uint32_t a=state[0],b=state[1],c=state[2],d=state[3],e=state[4],f=state[5],g=state[6],h=state[7];
        for (int i = 0; i < 64; ++i) {{
            const std::uint32_t s1 = Rotr(e,6) ^ Rotr(e,11) ^ Rotr(e,25);
            const std::uint32_t ch = (e & f) ^ ((~e) & g);
            const std::uint32_t t1 = h + s1 + ch + k[i] + w[i];
            const std::uint32_t s0 = Rotr(a,2) ^ Rotr(a,13) ^ Rotr(a,22);
            const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t t2 = s0 + maj;
            h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
        }}
        state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
        state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
    }}
    void Update(const unsigned char* data, std::size_t size) noexcept {{
        length += size;
        for (std::size_t i = 0; i < size; ++i) {{
            block[fill++] = data[i];
            if (fill == 64) {{ Compress(block); fill = 0; }}
        }}
    }}
    void Finish(unsigned char out[32]) noexcept {{
        const std::uint64_t bits = length * 8;
        const unsigned char pad = 0x80;
        Update(&pad, 1);
        const unsigned char zero = 0;
        while (fill != 56) Update(&zero, 1);
        unsigned char tail[8];
        for (int i = 0; i < 8; ++i) tail[i] = static_cast<unsigned char>(bits >> (56 - 8*i));
        Update(tail, 8);
        for (int i = 0; i < 8; ++i) {{
            out[i*4]   = static_cast<unsigned char>(state[i] >> 24);
            out[i*4+1] = static_cast<unsigned char>(state[i] >> 16);
            out[i*4+2] = static_cast<unsigned char>(state[i] >> 8);
            out[i*4+3] = static_cast<unsigned char>(state[i]);
        }}
    }}
}};

bool WriteCapture(const char* stem, mt::CaptureSink& sink, std::uint64_t owner,
                  std::size_t& outBytes, char outSha256[65]) {{
    static std::vector<unsigned char> buffer(1u << 20);
    const std::size_t encoded = mt::EncodeCapture(buffer.data(), buffer.size(), sink, owner);
    if (!encoded) return false;
    char path[512];
    std::snprintf(path, sizeof(path), "%s/%s.mwcap", g_outputDirectory, stem);
    std::FILE* handle = std::fopen(path, "wb");
    if (!handle) return false;
    const std::size_t written = std::fwrite(buffer.data(), 1, encoded, handle);
    std::fclose(handle);
    if (written != encoded) return false;
    outBytes = encoded;
    if (outSha256) {{
        Sha256 digest; digest.Init();
        digest.Update(buffer.data(), encoded);
        unsigned char raw[32]; digest.Finish(raw);
        for (int i = 0; i < 32; ++i) std::snprintf(outSha256 + i * 2, 3, "%02x", raw[i]);
        outSha256[64] = '\\0';
    }}
    std::printf("capture %s bytes=%zu records=%u sha256=%s\\n",
                path, encoded, sink.records, outSha256 ? outSha256 : "-");
    return true;
}}

bool WriteManifest(const char* stem, const mt::MountResult& result, std::uint64_t owner,
                   const char* captureSha, std::size_t captureBytes,
                   std::int32_t attachedKind, std::int32_t requestedKind) {{
    char path[512];
    std::snprintf(path, sizeof(path), "%s/%s.manifest.json", g_outputDirectory, stem);
    std::FILE* handle = std::fopen(path, "wb");
    if (!handle) return false;
    std::fprintf(handle,
        "{{\\n"
        "  \\"format\\": \\"MWMANIFEST\\",\\n"
        "  \\"version\\": 1,\\n"
        "  \\"tool\\": \\"{TOOL}\\",\\n"
        "  \\"toolVersion\\": {TOOL_VERSION},\\n"
        "  \\"module\\": \\"{MODULE}\\",\\n"
        "  \\"capture\\": {{\\"file\\": \\"%s.mwcap\\", \\"sha256\\": \\"%s\\", \\"bytes\\": %zu}},\\n"
        "  \\"source\\": {{\\"provenance\\": \\"STUB_IN_PROCESS\\", "
        "\\"note\\": \\"进程内自建桩内存，不是游戏进程、不是游戏写入\\"}},\\n"
        "  \\"requestedKind\\": %d,\\n"
        "  \\"outcome\\": \\"%s\\",\\n"
        "  \\"attachCalled\\": %s,\\n"
        "  \\"owner\\": %llu,\\n"
        "  \\"before\\": {{\\"rowCount\\": %u, \\"rows\\": [\\n",
        stem, captureSha, captureBytes, requestedKind,
        mt::MountCodeName(result.code), result.attach_called ? "true" : "false",
        static_cast<unsigned long long>(owner), result.before.count);
    for (std::uint32_t i = 0; i < result.before.count; ++i) {{
        const mt::ComponentRow& row = result.before.rows[i];
        std::fprintf(handle,
            "    {{\\"kind\\": %d, \\"wrapper\\": %llu, \\"config\\": %llu, \\"enabled\\": %u}}%s\\n",
            row.kind, static_cast<unsigned long long>(row.wrapper),
            static_cast<unsigned long long>(row.config), row.enabled,
            (i + 1u < result.before.count) ? "," : "");
    }}
    std::fprintf(handle, "  ]}},\\n  \\"declared\\": {{\\"rowCount\\": %u, \\"listCount\\": %u, "
                         "\\"setCount\\": %u, \\"kinds\\": [",
                 result.after.count, result.after.list_count, result.after.set_count);
    for (std::uint32_t i = 0; i < result.after.count; ++i) {{
        std::fprintf(handle, "%d%s", result.after.rows[i].kind,
                     (i + 1u < result.after.count) ? ", " : "");
    }}
    std::fprintf(handle, "], \\"rows\\": [\\n");
    for (std::uint32_t i = 0; i < result.after.count; ++i) {{
        const mt::ComponentRow& row = result.after.rows[i];
        std::fprintf(handle,
            "    {{\\"kind\\": %d, \\"wrapper\\": %llu, \\"config\\": %llu, \\"enabled\\": %u, "
            "\\"wrapperClass\\": %llu, \\"configClass\\": %llu}}%s\\n",
            row.kind, static_cast<unsigned long long>(row.wrapper),
            static_cast<unsigned long long>(row.config), row.enabled,
            static_cast<unsigned long long>(row.wrapper_class),
            static_cast<unsigned long long>(row.config_class),
            (i + 1u < result.after.count) ? "," : "");
    }}
    std::fprintf(handle,
        "  ]}},\\n  \\"kindRequested\\": %d,\\n  \\"kindAttached\\": %d,\\n  \\"writesGameBytes\\": false,\\n"
        "  \\"honestNote\\": \\"本 manifest 是**声明**。readback.py 不 import 本写入器，"
        "它自己解析 mwcap 重推结构，再与本声明比对；声明错即读回失败。\\"\\n}}\\n",
        requestedKind, attachedKind);
    std::fclose(handle);
    std::printf("manifest %s\\n", path);
    return true;
}}

}}  // namespace

int main(int argc, char** argv) {{
    g_outputDirectory = argc > 1 ? argv[1] : ".";
    g_region = VirtualAlloc(reinterpret_cast<void*>(kBase), kRegionBytes,
                            MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!g_region) {{
        std::printf("FAIL stub VirtualAlloc at 0x%llx (error %lu)\\n",
                    static_cast<unsigned long long>(kBase), GetLastError());
        return 1;
    }}
    std::memset(g_region, 0, kRegionBytes);

    // --- 桩内存布局 -------------------------------------------------------
    PutU<std::uint64_t>(kOwnerAddress + mt::kOwnerClassOffset, kClassAddress);
    PutU<std::uint64_t>(kOwnerAddress + mt::kOwnerSetOffset, kSetAddress);
    PutU<std::uint64_t>(kOwnerAddress + mt::kOwnerListOffset, kListAddress);
    PutU<unsigned char>(kOwnerAddress + mt::kOwnerStateOffset, 1);
    PutU<std::uint64_t>(kSetAddress + 0x00, kClassAddress);
    PutU<std::uint64_t>(kSetAddress + mt::kSetBucketsOffset, kBucketsAddress);
    PutU<std::uint64_t>(kSetAddress + mt::kSetSlotsOffset, kSlotsAddress);
    PutU<std::int32_t>(kSetAddress + mt::kSetCountOffset, 0);
    PutU<std::int32_t>(kSetAddress + mt::kSetLastIndexOffset, static_cast<std::int32_t>(kSlots));
    // 空集合 = count 0、lastIndex 等于容量、**空闲链表从 slot 0 起串满全部 64 槽**。
    // freeHead 必须是链首（0），不是 -1：-1 只在 lastIndex 也为 0 时才合法
    // （共享件 component_attachment.cpp:79-80 的 ``!count && !last && free_head == -1``）。
    PutU<std::int32_t>(kSetAddress + mt::kSetFreeHeadOffset, 0);
    PutU<std::uint64_t>(kListAddress + 0x00, kClassAddress);
    PutU<std::uint64_t>(kListAddress + mt::kSetBucketsOffset, kItemsAddress);
    PutU<std::int32_t>(kListAddress + mt::kArrayHeaderCountOffset, 0);
    PutU<std::int32_t>(kItemsAddress + mt::kArrayHeaderCountOffset, 0);
    PutU<std::int32_t>(kBucketsAddress + mt::kArrayHeaderCountOffset, static_cast<std::int32_t>(kSlots));
    PutU<std::int32_t>(kSlotsAddress + mt::kArrayHeaderCountOffset, static_cast<std::int32_t>(kSlots));
    for (std::size_t i = 0; i < kSlots; ++i) {{
        PutU<std::int32_t>(kBucketsAddress + mt::kArrayElementOffset + i * 4, -1);   // 空桶
        const std::uint64_t slot = kSlotsAddress + mt::kArrayElementOffset + i * mt::kSlotBytes;
        PutU<std::int32_t>(slot, -1);                                             // hash（空闲槽无意义）
        // **空闲链表必须真的串起来**：next[i] = i+1，末项 -1。
        // 首版把 next 一律写 -1，于是 freeHead=0 时走一步就结束、
        // 剩下 63 个槽既不在链上也不在空闲链里 ⇒ free_list_bad_link。
        PutU<std::int32_t>(slot + 4, i + 1 < kSlots ? static_cast<std::int32_t>(i + 1) : -1);
        PutU<std::int32_t>(slot + 8, -1);                                         // value（空闲槽无意义）
    }}

    mt::ReadSource source{{StubRead, nullptr}};
    // **每次挂载一个独立 sink**：一个 sink 跨多次挂载会让同一地址被读到不同内容
    // （挂载会改 count），而独立读回会把那判成 capture_region_unstable ——
    // 那是**正确**的拒绝（实测踩过），所以主捕获必须只覆盖一次挂载。
    static std::vector<unsigned char> sinkBytes(1u << 20);
    static std::vector<unsigned char> sinkBytes2(1u << 20);
    mt::Workspace workspace;
    mt::MountResult result;
    mt::MountEvidence evidence{{kOwnerAddress, kClassAddress, kClassAddress, kClassAddress,
                                kKindFirst, true}};
    mt::MountRequest request{{kOwnerAddress, kKindFirst, evidence}};
    mt::CaptureSink sink{{sinkBytes.data(), sinkBytes.size(), 0, 0, false}};
    mt::CaptureSink sink2{{sinkBytes2.data(), sinkBytes2.size(), 0, 0, false}};

    // 1) 正常挂载：0 → 1，且调用恰好一次。
    RunMount("mount1-first", source, &AttachHook, request, workspace, &sink, result);
    // 失败时把两个快照码打出来：否则「before 失败」与「after 失败」长得一样。
    if (result.code != mt::MountCode::attached_verified) {{
        std::printf("diag mount=%s before=%s/%s(set=%u,list=%u,cap=%u) after=%s/%s\\n",
                    mt::MountCodeName(result.code), mt::SnapshotCodeName(result.before.code),
                    result.before.stage ? result.before.stage : "-",
                    result.before.set_count, result.before.list_count, result.before.set_capacity,
                    mt::SnapshotCodeName(result.after.code),
                    result.after.stage ? result.after.stage : "-");
        std::printf("diag fault=%s bucket=%u head=%d lastIndex=%d capacity=%u firstBucket=%d\\n",
                    mt::g_fault.stage, mt::g_fault.bucket, mt::g_fault.head,
                    mt::g_fault.last_index, mt::g_fault.capacity, mt::g_fault.first_bucket);
        std::printf("diag setPtr=0x%llx bucketsPtr=0x%llx slotsPtr=0x%llx itemsPtr=0x%llx\\n",
                    (unsigned long long)mt::g_fault.set_ptr,
                    (unsigned long long)mt::g_fault.buckets_ptr,
                    (unsigned long long)mt::g_fault.slots_ptr,
                    (unsigned long long)mt::g_fault.items_ptr);
        std::printf("diag setHeader=");
        for (std::size_t i = 0; i < sizeof(mt::g_fault.set_header); ++i)
            std::printf("%02x", static_cast<unsigned>(mt::g_fault.set_header[i]));
        std::printf("\\n");
        std::printf("diag calls snapshotOwner=%u readStructures=%u parseSet=%u\\n",
                    mt::g_snapshotOwnerCalls, mt::g_readStructuresCalls, mt::g_parseSetCalls);
    }}
    Check(result.code == mt::MountCode::attached_verified, "mount: attached_verified");
    Check(g_attachCalls == 1, "mount: attach called exactly once");
    Check(result.before.count == 0 && result.after.count == 1, "mount: count 0 -> 1");
    Check(result.returned_wrapper == result.component.wrapper, "mount: returned wrapper matches added row");
    Check(result.after.rows[0].kind == request.kind, "mount: added row kind matches");
    const std::uint32_t countAfterFirst = result.after.count;
    const std::uint64_t wrapperAfterFirst = result.component.wrapper;

    // 2) 幂等：同 kind 第二次 ⇒ existing，不再调用。
    const std::int32_t callsAfterFirst = g_attachCalls;
    mt::MountResult again;
    RunMount("mount2-idempotent", source, &AttachHook, request, workspace, nullptr, again);
    Check(again.code == mt::MountCode::existing, "idempotent: existing");
    Check(g_attachCalls == callsAfterFirst, "idempotent: attach NOT called again");

    // 3) 第二个 kind 追加 ⇒ 前缀必须原样（1 → 2）。
    mt::MountEvidence second = evidence;
    second.kind = kKindSecond;
    mt::MountRequest secondRequest{{kOwnerAddress, second.kind, second}};
    mt::MountResult secondResult;
    RunMount("mount3-second", source, &AttachHook, secondRequest, workspace, &sink2, secondResult);
    Check(secondResult.code == mt::MountCode::attached_verified, "second kind: attached_verified");
    Check(secondResult.before.count == countAfterFirst &&
          secondResult.after.count == countAfterFirst + 1, "second kind: count +1");
    Check(secondResult.after.rows[0].wrapper == wrapperAfterFirst, "second kind: prefix row untouched");

    // 4) 未知 kind 被拒。
    mt::MountRequest bad = request;
    bad.kind = 9999; bad.evidence.kind = 9999;
    mt::MountResult badResult;
    RunMount("mount4-unknown", source, &AttachHook, bad, workspace, nullptr, badResult);
    Check(badResult.code == mt::MountCode::unknown_kind, "unknown kind refused");

    // 5) 缺 attach 绑定被拒（用**完全没碰过**的 kind）。
    //    kKindFirst / kKindSecond 已经被挂过；kKindFourth 是本次集合里下一个干净的。
    //    用错会先命中 existing 短路，断言就永远测不到 missing_binding。
    mt::MountEvidence fourth = evidence;
    fourth.kind = kKindFourth;
    mt::MountRequest fourthRequest{{kOwnerAddress, kKindFourth, fourth}};
    mt::MountResult none;
    RunMount("mount5-noBinding", source, nullptr, fourthRequest, workspace, nullptr, none);
    CheckEq("missing binding refused", static_cast<int>(none.code),
            static_cast<int>(mt::MountCode::missing_binding));

    // 6) 身份不符被拒（evidence.owner_class 与实体实际不符）。
    mt::MountEvidence wrong = fourth;
    wrong.owner_class = kClassAddress + kStride;
    mt::MountRequest wrongReq{{kOwnerAddress, kKindFourth, wrong}};
    mt::MountResult wrongResult;
    RunMount("mount6-identity", source, &AttachHook, wrongReq, workspace, nullptr, wrongResult);
    CheckEq("identity mismatch refused", static_cast<int>(wrongResult.code),
            static_cast<int>(mt::MountCode::identity_mismatch));

    // 7) 返回空 ⇒ null_return（前缀与上下文都对，只有返回值不对）。
    //    桩式 attach 在返回空**之前已经追加了一行**，所以这个 kind 到此被占用。
    mt::MountResult nullResult;
    g_attachReturnsNull = true;
    RunMount("mount7-nullReturn", source, &AttachHook, fourthRequest, workspace, nullptr, nullResult);
    g_attachReturnsNull = false;
    CheckEq("null return refused", static_cast<int>(nullResult.code),
            static_cast<int>(mt::MountCode::null_return));

    // 8) 抛异常 ⇒ call_exception。
    mt::MountResult throwResult;
    g_attachThrows = true;
    RunMount("mount8-throws", source, &AttachHook, fourthRequest, workspace, nullptr, throwResult);
    g_attachThrows = false;
    CheckEq("call exception recorded", static_cast<int>(throwResult.code),
            static_cast<int>(mt::MountCode::call_exception));

    // 9) 前缀被改 ⇒ prefix_changed。
    //    用一个**与本实体无关**的新 kind（kKindExtra，默认取枚举尾部的高位 kind），
    //    这样它一定不在 before 里，于是真的会走到「调用 attach → 再比前缀」。
    //    错的字段也有讲究，三种错法各命中不同的守卫（都实测过）：
    //      · 改 ``kind`` ⇒ 快照在 before 阶段就 set_list_disagree（另一条守卫）；
    //      · 改 config 的 ``backref`` ⇒ ReadRow 的回指核对失败 ⇒ before_failed；
    //      · 改 ``enabled`` ⇒ 行仍然**可读且结构自洽**，但 PrefixUnchanged 的逐字段
    //        memcmp 会发现它变了 ⇒ 这才是真正命中 prefix_changed 的错法。
    mt::MountEvidence extra = evidence;
    extra.kind = kKindExtra;
    mt::MountRequest extraRequest{{kOwnerAddress, kKindExtra, extra}};
    static std::vector<unsigned char> prefixSinkBytes(1u << 20);
    mt::CaptureSink prefixSink{{prefixSinkBytes.data(), prefixSinkBytes.size(), 0, 0, false}};
    mt::MountResult prefixResult;
    // 行地址不是 kRowBase：它是 LIST 的 ``items[0]``。用错地址就等于什么都没改
    // （第一次写这段时正是在 kRowBase 上动的手，结果 prefix 用例「通过」了追加）。
    // 改动必须发生在 **attach 调用内部**（g_corruptPrefixOnAttach）：
    // 在调用前后改同一份内存，before 与 after 会读到同一个值，前缀比较照样通过。
    g_corruptPrefixOnAttach = true;
    RunMount("mount9-prefix", source, &AttachHook, extraRequest, workspace, &prefixSink, prefixResult);
    g_corruptPrefixOnAttach = false;
    CheckEq("prefix change refused", static_cast<int>(prefixResult.code),
            static_cast<int>(mt::MountCode::prefix_changed));
    // 正控：证明守卫**真的看到了**差异，而不是因为别的原因失败。
    // before 的第 0 行是挂载前读到的（enabled=1），after 的是调用后读到的（被改成 200）。
    Check(prefixResult.before.rows[0].enabled != prefixResult.after.rows[0].enabled,
          "prefix test: before/after row 0 really differ (positive control)");

    // 10) kind 表：请求的 kind 在、9999 不在、哨兵 47 不在。
    Check(mt::KnownKind(kKindFirst), "kind table: requested kind present");
    Check(!mt::KnownKind(9999), "kind table: 9999 absent");
    Check(!mt::KnownKind(47), "kind table: sentinel 47 absent");
    Check(g_ownerMismatch == 0, "attach hook: owner argument was always the stub entity");

    // 11) **独立可重算的追加证据**：再做一次干净挂载，**分别**捕获 before 与 after。
    //     读回（readback.derive_append_pair）拿这两份字节自己重算：
    //     行数 +1、既有行逐字段守恒、新增行的身份。不靠任何 summary。
    mt::MountEvidence verifiable = evidence;
    verifiable.kind = kKindSixth;
    mt::MountRequest verifiableRequest{{kOwnerAddress, kKindSixth, verifiable}};
    static std::vector<unsigned char> verifySinkBytes[2];
    verifySinkBytes[0].assign(1u << 20, 0);
    verifySinkBytes[1].assign(1u << 20, 0);
    mt::CaptureSink preSink{{verifySinkBytes[0].data(), verifySinkBytes[0].size(), 0, 0, false}};
    mt::CaptureSink postSink{{verifySinkBytes[1].data(), verifySinkBytes[1].size(), 0, 0, false}};
    mt::MountResult pairResult;
    RunMountPair("mount11-verifiable", source, &AttachHook, verifiableRequest, workspace,
                 &preSink, &postSink, pairResult);
    Check(pairResult.code == mt::MountCode::attached_verified,
          "verifiable pair: attached_verified");
    Check(pairResult.after.count == pairResult.before.count + 1,
          "verifiable pair: after has exactly one more row than before");

    // 11) 落盘：
    //     · ``capture.mwcap`` = 一次挂载的 **after 侧**（字节自洽：每个地址只读到一个值）；
    //     · ``capture-before.mwcap`` = 同一挂载的 **before 侧**；
    //     · ``capture-prefix-changed.mwcap`` = 前缀被改那次挂载的读数。
    //     **不能用同一个 sink 同时收 before 与 after**：同一地址会被读到两个值，
    //     独立读回会（正确地）判 capture_region_unstable —— 那是拒绝，不是通过。
    std::size_t captureBytes = 0;
    char captureSha[65] = {{0}};
    if (!WriteCapture("capture", postSink, kOwnerAddress, captureBytes, captureSha)) {{
        std::printf("FAIL capture write\\n"); ++g_failures;
    }}
    Check(postSink.records > 0 && !postSink.overflow, "main capture has records and no overflow");
    CaptureBytes = captureBytes;
    std::size_t beforeBytes = 0, prefixBytes = 0;
    char beforeSha[65] = {{0}}, prefixSha[65] = {{0}};
    if (!WriteCapture("capture-before", preSink, kOwnerAddress, beforeBytes, beforeSha)) {{
        std::printf("FAIL before capture write\\n"); ++g_failures;
    }}
    if (!WriteCapture("capture-prefix-changed", prefixSink, kOwnerAddress, prefixBytes, prefixSha)) {{
        std::printf("FAIL prefix capture write\\n"); ++g_failures;
    }}
    if (!WriteManifest("capture", pairResult, kOwnerAddress, captureSha, captureBytes,
                       verifiable.kind, verifiable.kind)) {{
        std::printf("FAIL manifest write\\n"); ++g_failures;
    }}
    if (!WriteManifest("capture-before", pairResult, kOwnerAddress, beforeSha, beforeBytes,
                       verifiable.kind, verifiable.kind)) {{
        std::printf("FAIL before manifest write\\n"); ++g_failures;
    }}
    std::printf("DRIVER_%s failures=%d attachCalls=%d captureBytes=%zu prefixBytes=%zu\\n",
                g_failures ? "FAILED" : "OK", g_failures, g_attachCalls, CaptureBytes, prefixBytes);
    return g_failures ? 1 : 0;
}}
'''


def write_native_sources(
    out_dir: Path,
    *,
    anchors: dict[str, Anchor],
    kinds: Sequence[int],
) -> dict:
    """把 TU 与驱动写到 ``out_dir``（**工程内**；本工具不写工程外）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tu = emit_native_tu(anchors=anchors, kinds=kinds)
    driver = emit_driver_tu(kinds=kinds)
    if "native_tabs" in tu or "generalized_tabs" in tu or "#include \"" in tu:
        raise MounterError(
            "TU_FORBIDDEN_TOKEN",
            "生成的 TU 含禁项（native_tabs / generalized_tabs / 工程内 #include）",
        )
    tu_path = out_dir / "component_mounter_native.cpp"
    driver_path = out_dir / "mounter_driver.cpp"
    tu_path.write_text(tu, encoding="utf-8")
    driver_path.write_text(driver, encoding="utf-8")
    return {
        "tuPath": tu_path.as_posix(),
        "driverPath": driver_path.as_posix(),
        "tuBytes": len(tu.encode("utf-8")),
        "driverBytes": len(driver.encode("utf-8")),
        "tuSha256": hashlib.sha256(tu.encode("utf-8")).hexdigest(),
        "driverSha256": hashlib.sha256(driver.encode("utf-8")).hexdigest(),
        "layoutId": CAPTURE_LAYOUT_ID,
        "captureVersion": CAPTURE_VERSION,
        "captureLayout": CAPTURE_LAYOUT,
    }


# ---------------------------------------------------------------------------
# 依赖树
# ---------------------------------------------------------------------------
def dependency_tree() -> dict:
    """本工具**只读**依赖的实测状态。含「本工具有没有改过 component_attachment.*」。"""
    rows = []
    for label, path in (
        ("runtime-profile (ABI anchors)", RUNTIME_PROFILE),
        ("shared ABI header (signature)", SHARED_ABI_HEADER),
        ("kind enum source", KIND_ENUM_SOURCE),
        ("world contract", WORLD_CONTRACT),
    ):
        full = path if path.is_absolute() else REPO_ROOT / path
        rows.append({
            "label": label,
            "path": path.as_posix(),
            "exists": full.is_file(),
            "sha256": _sha256_file(full) if full.is_file() else None,
            "access": "read-only",
            "writtenByThisTool": False,
        })
    cpp = REPO_ROOT / "tools/game-executor/template-authoring/component_attachment.cpp"
    header = REPO_ROOT / "tools/game-executor/template-authoring/component_attachment.h"
    return {
        "ok": all(row["exists"] for row in rows),
        "step": "check-deps",
        "dependsOn": rows,
        "image": {
            "path": str(DEFAULT_IMAGE),
            "exists": DEFAULT_IMAGE.is_file(),
            "access": "read-only (anchor verification only)",
            "writtenByThisTool": False,
        },
        "sharedPrimitiveBoundary": {
            "files": [cpp.as_posix(), header.as_posix()],
            "modifiedByThisTool": False,
            "statement": (
                "本工具**没有**修改 component_attachment.{h,cpp}；那里 {17,33,35} 的白名单"
                "属于 native-options 的写范围。combat 走本目录的独立实现（world-contract v26 "
                "componentWriterBoundary.implementation.dir / deliveryDefinition."
                "acceptanceSemantics.missingLowLevel）。"
            ),
            "sharedHeaderSha256": _sha256_file(header) if header.is_file() else None,
            "sharedSourceSha256": _sha256_file(cpp) if cpp.is_file() else None,
        },
        "ownWrites": {
            "writesGameBytes": False,
            "writesOutsideRepo": False,
            "note": "只在 --emit-tu 给的目录里写生成的 .cpp（默认 .runtime/mondstadt/combat/）。",
        },
    }


# ---------------------------------------------------------------------------
# 回执
# ---------------------------------------------------------------------------
def receipt(step: str, payload: dict, ok: bool, *, blocked: str | None = None) -> dict:
    """runner 回执。``ok`` 由调用方按**真实判定**给，绝不无脑 True。"""
    doc = {
        "ok": bool(ok),
        "step": step,
        "tool": TOOL,
        "toolVersion": TOOL_VERSION,
        "module": MODULE,
        "contractVersion": CONTRACT_VERSION,
        "captureFormat": CAPTURE_FORMAT,
        "captureVersion": CAPTURE_VERSION,
        "captureLayoutId": CAPTURE_LAYOUT_ID,
        "writesGameBytes": False,
        "outcomeUncertain": False,
        "payload": payload,
    }
    if blocked:
        doc["blockedReason"] = blocked
    return doc


# ===========================================================================
# 共享原生通道：prepare（一次性候选目录） + compile-check（只编译不派发）
# ===========================================================================
#: 固定根（leader 预留）：source-run 一律落在这里，**不接受调用方指定别的根**。
FIXED_ROOT = Path(".runtime/mondstadt-native/combat/prepared")
#: 允许的写根。``.runtime-verify`` 只在 ``--root`` 显式给出时用于**本机端到端验证**
#: （本会话里沙箱拒绝子进程写 ``.runtime/**``），产物不得当作正式候选。
ALLOWED_WRITE_ROOTS: tuple[Path, ...] = (Path(".runtime"), Path(".runtime-verify"))
#: 固定 kind 标识（leader 预留）。
FIXED_KIND = "mondstadt-combat-build-v1"
#: 固定 action 号（leader 预留 21）与 receipt 协议号（leader 预留 26）。
FIXED_ACTION_CODE = 21
FIXED_RECEIPT_VERSION = 26
#: 固定 wrapper 名（每次生成同一份，不是现写）。
FIXED_WRAPPER_NAME = "invoke-mondstadt-combat.ps1"
#: 固定 scope 串（wrapper 的 exit.json 必须写它）。
FIXED_SCOPE = "FIXED_MONDSTADT_COMBAT_ACTION"

#: 只读借用的共享原生源（**不修改**，只复制）。
SHARED_NATIVE_SOURCES: tuple[str, ...] = (
    "game_context_snapshot.cpp",
    "game_context_snapshot.h",
    "hook_receipt.cpp",
    "hook_receipt_probe.cpp",
    "hook_receipt_protocol.h",
)
#: 共享源里**不得被本模块改动**的文件（依赖树里显式核对 sha256 未变）。
SHARED_MUST_NOT_CHANGE: tuple[str, ...] = (
    "tools/game-executor/native-options/build_generalized.py",
    "tools/game-executor/template-authoring/component_attachment.h",
    "tools/game-executor/template-authoring/component_attachment.cpp",
)


def read_json_safe(path: Path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: 默认热修字节 RVA（**只读借用**：读自同一份 runtime-profile.json，
#: 与 ``build_generalized.py`` 用的一组同源；本文件不自己造一份）。
DEFAULT_HOTFIX_BYTE_RVAS: tuple[str, ...] = (
    "0x56e8ca5", "0x56e8ca6", "0x56e9602", "0x56e9637",
)


def _load_hotfix_rvas(profile_path: Path = RUNTIME_PROFILE) -> tuple[str, ...]:
    path = profile_path if profile_path.is_absolute() else REPO_ROOT / profile_path
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return DEFAULT_HOTFIX_BYTE_RVAS
    rows = [str(x) for x in (doc.get("hotfixZeroRvas") or [])]
    return tuple(rows) if rows else DEFAULT_HOTFIX_BYTE_RVAS


def gettickcount64() -> int:
    """``GetTickCount64`` —— deadline 必须与探针同源，**不能用 Unix 毫秒**。

    探针侧的比较是 ``GetTickCount64() > HR_DEADLINE``；若 deadline 来自 Unix 纪元，
    两个时钟不同源，跨开机/休眠后该比较失去意义。
    """
    import ctypes as C
    if not hasattr(gettickcount64, "_fn"):
        kernel32 = C.WinDLL("kernel32", use_last_error=True)
        kernel32.GetTickCount64.restype = C.c_ulonglong
        gettickcount64._fn = kernel32.GetTickCount64  # type: ignore[attr-defined]
    return int(gettickcount64._fn())  # type: ignore[attr-defined]


def _session_from_file(path: Path) -> dict:
    # **具名**：缺文件与坏 JSON 是两种不同的错，各给一个 code（泛化的 OS_ERROR 不告诉你
    # 是路径错了还是内容错了）。实测：旧版对不存在的 --session 会裸抛 FileNotFoundError。
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise MounterError("SESSION_FILE_MISSING", f"--session {path} 不存在") from None
    except OSError as exc:
        raise MounterError(
            "SESSION_FILE_UNREADABLE",
            f"--session {path} 读不了：{type(exc).__name__}: {exc}"
            f"（winerror={getattr(exc, 'winerror', None)}）",
        ) from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MounterError(
            "SESSION_FILE_JSON_INVALID",
            f"--session {path} 第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
        ) from None
    if not isinstance(doc, dict):
        raise MounterError("SESSION_FILE_NOT_OBJECT", f"{path} 不是 JSON 对象")
    return doc


def resolve_session(*, session_path: str | None, discover: bool,
                    deadline_seconds: int) -> tuple[dict, int, dict]:
    """真实 TargetProcess 身份 + GetTickCount64 域的 deadline。

    返回 ``(session, deadline_ms, note)``。**绝不返回 pid=tid=1 的占位**：
    没有真实来源时具名拒绝，由调用方决定是否降级到「编译占位」（那条路径
    会把 ``identityPlaceholder=True`` 写进回执）。
    """
    note: dict = {"sessionSource": None, "sessionVerified": False, "warnings": []}
    session: dict | None = None
    if session_path:
        raw = _session_from_file(Path(session_path))
        session = dict(raw.get("session") or raw)
        note["sessionSource"] = f"file:{session_path}"
    elif discover:
        # **只读复用** native_profiles 的现读身份（不改共享件）。
        extra = REPO_ROOT / "tools/game-executor"
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
        try:
            import native_profiles as profiles  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise MounterError("NATIVE_PROFILES_UNAVAILABLE", str(exc)) from None
        try:
            session = profiles.discover_session()
            session = profiles.validate_session(session)
        except Exception as exc:  # noqa: BLE001 - ProfileError/OSError both mean "no session"
            raise MounterError(
                "NO_VERIFIED_TARGET_SESSION",
                f"现读目标会话失败（{type(exc).__name__}: {exc}）；"
                "没有真实身份就**不得**编造 pid/tid，也不得写 1",
            ) from None
        note["sessionSource"] = "native_profiles.discover_session()+validate_session()"
    if session is None:
        raise MounterError(
            "NO_VERIFIED_TARGET_SESSION",
            "缺真实 TargetProcess 身份。给 --session <json>（现读留档）或 --discover-session。"
            "**不接受 pid=tid=creation=1 的占位**；若只想编译，请用 --compile-placeholder。",
        )
    required = ("pid", "tid", "processCreation", "threadCreation")
    missing = [k for k in required if not isinstance(session.get(k), int) or session.get(k) in (0, 1)]
    if missing:
        raise MounterError(
            "SESSION_IDENTITY_INCOMPLETE",
            f"会话缺真实取值或仍是占位：{missing}；piD/TID/creation 都必须来自现读",
        )
    note["sessionVerified"] = True
    deadline_ms = gettickcount64() + max(1, int(deadline_seconds)) * 1000
    note["deadlineClock"] = "GetTickCount64"
    return session, deadline_ms, note


def _require_inside_runtime(path: Path, *, allowed_roots: tuple[Path, ...] | None = None) -> Path:
    """写范围闸：只允许工程内的 .runtime/（正式）或显式的验证根。

    ``--root`` 是**本地验证用的缝**（本机会话里沙箱拒写 ``.runtime/**``），
    因此它必须显式写出，且回执里会留下 ``rootPolicy``。默认路径永远是固定根。
    """
    resolved = path.resolve()
    roots = allowed_roots or (REPO_ROOT / ".runtime",)
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise MounterError(
            "OUTPUT_MUST_BE_PROJECT_RUNTIME",
            f"{resolved} 不在允许的写范围内 "
            + " 或 ".join(root.as_posix() for root in roots),
        )
    return resolved


def _new_run_directory(root_override: str | None = None) -> tuple[Path, dict]:
    import secrets
    from datetime import datetime
    if root_override:
        root = Path(root_override)
        if not root.is_absolute():
            root = REPO_ROOT / root
        root = _require_inside_runtime(root, allowed_roots=ALLOWED_WRITE_ROOTS)
        note = {
            "rootOverridden": True,
            "fixedRoot": FIXED_ROOT.as_posix(),
            "usedRoot": root.relative_to(REPO_ROOT).as_posix(),
            # 诚实字段：本会话**从未在固定根上端到端跑过**（沙箱子进程拒写 .runtime/**）。
            # 等 runner/root（有写权限）在固定根上真跑过一次才可翻 true。
            "fixedRootExercised": False,
            "why": (
                "调用方用 --root 覆盖了固定根。**这不符合 leader 预留的根约定**"
                "（.runtime/mondstadt-native/combat/prepared/）；只应在固定根不可写"
                "（例如沙箱拒绝写 .runtime）时用于本地端到端验证，产物不得当作正式候选。"
            ),
        }
    else:
        root = _require_inside_runtime(REPO_ROOT / FIXED_ROOT)
        note = {
            "rootOverridden": False,
            "fixedRoot": FIXED_ROOT.as_posix(),
            "usedRoot": FIXED_ROOT.as_posix(),
            "why": "使用 leader 预留的固定根。",
            "fixedRootExercised": False,
        }
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(5)
    run = root / stamp
    run.mkdir(parents=True, exist_ok=False)
    return run, note


def _shared_source_hashes() -> dict[str, str]:
    """所有会被碰的共享文件的 sha256（**编辑前后各取一次**，用来证明只改了副本）。"""
    origin = REPO_ROOT / "tools/game-executor/native"
    names = set(SHARED_NATIVE_SOURCES) | set(_source_edits())
    out: dict[str, str] = {}
    for name in sorted(names):
        path = origin / name
        rel = path.relative_to(REPO_ROOT).as_posix()
        out[rel] = _sha256_file(path) if path.is_file() else "MISSING"
    return out


def _isolated_sources(run: Path, *, anchors: dict[str, Anchor],
                      kinds: Sequence[int] = ()) -> dict[str, str]:
    """把共享原生源**复制**进候选目录（隔离），并记录源文件 sha256。

    **编辑只发生在 ``candidate-source/native/`` 内**；共享件一个字节都不动
    （``_source_edits`` 给出全部改动行，``sharedSourceHashesBefore`` 给出 sha256 证据）。
    """
    dest = run / "candidate-source/native"
    dest.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    origin = REPO_ROOT / "tools/game-executor/native"
    for name in SHARED_NATIVE_SOURCES:
        source = origin / name
        if not source.is_file():
            raise MounterError("SHARED_SOURCE_MISSING", f"{source} 不存在")
        (dest / name).write_bytes(source.read_bytes())
        hashes[source.relative_to(REPO_ROOT).as_posix()] = _sha256_file(source)
    # 本模块自己的适配头 + 执行 TU：放进同一个 candidate-source/native/，于是
    # hook_receipt_protocol.h 里可以做**真正的** #include "combat_component_mount.h"。
    # **探针不在这里生成**：共享 hook_receipt_probe.cpp 已被复制进来，action 21 由
    # _source_edits() 在**副本**上扩展（owner ②：必须复用共享探针的真实协议流程 ——
    # 建 mapping、LoadLibrary、SetWindowsHookEx、PostThreadMessage、等 callback、
    # UnhookWindowsHookEx、收据 —— 不得拿一个不注入的程序冒充探针）。
    (dest / COMBAT_ADAPTER_HEADER).write_text(_combat_adapter_header(), encoding="utf-8")
    (dest / COMBAT_ADAPTER_IMPL).write_text(_combat_adapter_impl(kinds), encoding="utf-8")
    return hashes


#: 放进候选源树里的适配头名（与 hook_receipt_protocol.h 的 #include 逐字一致）。
COMBAT_ADAPTER_HEADER = "combat_component_mount.h"
#: 适配实现 TU：定义 ``ExecuteCombatComponentMount``，链接进 hook DLL。
COMBAT_ADAPTER_IMPL = "combat_component_mount.cpp"


def _combat_probe_source(anchors: dict[str, Anchor]) -> str:
    """固定探针：**真实 probe**，不是自测回显。

    两种模式：
    * 无参数 —— 打印身份/协议/锚点记录；``identityPlaceholder`` 时退出码 1；
    * ``--capture <mwcap>`` —— **自己解开原生捕获字节**，打印实体/组件表/每个
      组件的 (wrapper, wrapper_class, kind, config, config_class, enabled)。
      这是把「从实体读回」这件事做成可独立复核的**真实只读动作**。

    它**不派发、不注入、不加载、不碰游戏**：只读文件。
    """
    return f'''// {MODULE} / {TOOL}：固定 combat probe（由 component_mounter.py 生成）。
// **只读**：解身份/协议，或解开一份原生捕获字节。不注入、不加载、不派发、不碰游戏。
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "hook_receipt_protocol.h"

// 探针只用 C 运行时读文件；MSVC 在 /WX 下把 fopen 的 C4996 当错误，就地点名抑制。
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4996)
#endif

namespace {{

static_assert(HR_ACTION == {FIXED_ACTION_CODE}, "HR_ACTION must be the reserved combat action");
#if defined(MT_IDENTITY_PLACEHOLDER) && MT_IDENTITY_PLACEHOLDER == 1
inline constexpr bool kIdentityPlaceholder = true;
#else
inline constexpr bool kIdentityPlaceholder = false;
#endif

// --- 本探针自己的捕获解码器（偏移显式；不用隐式对齐的 struct） ---
constexpr std::size_t kHeaderBytes = 28;
constexpr std::size_t kOffVersion = 8, kOffRecords = 12, kOffOwner = 16;
constexpr std::size_t kRecordHeader = 12;
constexpr std::uint64_t kOwnerSetOffset = 0x30, kOwnerListOffset = 0x68;
constexpr std::uint64_t kArrayLengthOffset = 0x18, kArrayElementOffset = 0x20;
constexpr std::uint64_t kSetBucketsOffset = 0x10, kSetSlotsOffset = 0x20;
constexpr std::uint64_t kSetCountOffset = 0x28, kSetLastIndexOffset = 0x2C;
constexpr std::uint64_t kSetFreeHeadOffset = 0x30;
constexpr std::uint64_t kWrapperBytes = 0x38, kWrapperBackrefOffset = 0x20;
constexpr std::uint64_t kWrapperConfigOffset = 0x28, kWrapperEnabledOffset = 0x30;
constexpr std::uint64_t kWrapperKindOffset = 0x34;
constexpr std::uint64_t kConfigBackrefOffset = 0x18, kConfigOwnerOffset = 0x20;
constexpr std::uint64_t kSlotBytes = 12, kMaxComponents = 256;

struct Region {{ std::uint64_t address; std::vector<unsigned char> bytes; }};

bool Read(std::uint64_t address, void* target, std::size_t size,
          const std::vector<Region>& regions) {{
    for (const Region& region : regions) {{
        if (region.address <= address && address + size <= region.address + region.bytes.size()) {{
            std::memcpy(target, region.bytes.data() + (address - region.address), size);
            return true;
        }}
    }}
    return false;
}}

template <class T> bool At(std::uint64_t address, T& value, const std::vector<Region>& regions) {{
    return Read(address, &value, sizeof(value), regions);
}}

template <class T> T From(const unsigned char* bytes, std::size_t offset) {{
    T value{{}}; std::memcpy(&value, bytes + offset, sizeof(value)); return value;
}}

bool Ptr(std::uint64_t value) {{ return value >= 0x10000ULL && value < 0x0000800000000000ULL; }}

}}  // namespace

/// 解开一份 MWCAP 并打印结构。返回 0 成功、非 0 失败。
int DecodeCapture(const char* path) {{
    std::FILE* handle = std::fopen(path, "rb");
    if (!handle) {{ std::printf("{{\\"ok\\":false,\\"error\\":\\"capture_open_failed\\"}}\\n"); return 2; }}
    std::vector<unsigned char> data;
    unsigned char buffer[65536];
    std::size_t got = 0;
    while ((got = std::fread(buffer, 1, sizeof(buffer), handle)) > 0)
        data.insert(data.end(), buffer, buffer + got);
    std::fclose(handle);
    if (data.size() < kHeaderBytes || std::memcmp(data.data(), "MWCAP001", 8) != 0) {{
        std::printf("{{\\"ok\\":false,\\"error\\":\\"capture_bad_header\\"}}\\n");
        return 2;
    }}
    std::uint32_t version = 0, records = 0;
    std::uint64_t owner = 0;
    std::memcpy(&version, data.data() + kOffVersion, 4);
    std::memcpy(&records, data.data() + kOffRecords, 4);
    std::memcpy(&owner, data.data() + kOffOwner, 8);
    std::vector<Region> regions;
    std::size_t cursor = kHeaderBytes;
    for (std::uint32_t i = 0; i < records; ++i) {{
        if (cursor + kRecordHeader > data.size()) {{ std::printf("{{\\"ok\\":false,"
            "\\"error\\":\\"capture_record_truncated\\"}}\\n"); return 2; }}
        std::uint64_t address = 0; std::uint32_t length = 0;
        std::memcpy(&address, data.data() + cursor, 8);
        std::memcpy(&length, data.data() + cursor + 8, 4);
        cursor += kRecordHeader;
        if (cursor + length > data.size()) {{ std::printf("{{\\"ok\\":false,"
            "\\"error\\":\\"capture_record_body_truncated\\"}}\\n"); return 2; }}
        Region region; region.address = address;
        region.bytes.assign(data.begin() + cursor, data.begin() + cursor + length);
        regions.push_back(region);
        cursor += length;
    }}

    std::uint64_t set_ptr = 0, list_ptr = 0;
    if (!At(owner + kOwnerSetOffset, set_ptr, regions) ||
        !At(owner + kOwnerListOffset, list_ptr, regions)) {{
        std::printf("{{\\"ok\\":false,\\"error\\":\\"owner_roots_unreadable\\"}}\\n"); return 2;
    }}
    std::uint64_t items_ptr = 0;
    std::int32_t list_count = 0;
    if (!At(list_ptr + kSetBucketsOffset, items_ptr, regions) ||
        !At(list_ptr + kArrayLengthOffset, list_count, regions)) {{
        std::printf("{{\\"ok\\":false,\\"error\\":\\"list_header_unreadable\\"}}\\n"); return 2;
    }}

    std::printf("{{\\"ok\\":true,\\"captureVersion\\":%u,\\"records\\":%u,"
                "\\"owner\\":%llu,\\"rowCount\\":%d,\\"components\\":[",
                version, records, static_cast<unsigned long long>(owner), list_count);
    for (std::int32_t i = 0; i < list_count; ++i) {{
        std::uint64_t pointer = 0;
        if (!At(items_ptr + kArrayElementOffset + static_cast<std::uint64_t>(i) * 8,
                pointer, regions) || !Ptr(pointer)) break;
        unsigned char wrapper[kWrapperBytes];
        if (!Read(pointer, wrapper, sizeof(wrapper), regions)) break;
        const std::uint64_t wrapper_class = From<std::uint64_t>(wrapper, 0);
        const std::uint64_t backref = From<std::uint64_t>(wrapper, kWrapperBackrefOffset);
        const std::uint64_t config = From<std::uint64_t>(wrapper, kWrapperConfigOffset);
        const std::int32_t kind = From<std::int32_t>(wrapper, kWrapperKindOffset);
        const unsigned char enabled = wrapper[kWrapperEnabledOffset];
        std::uint64_t config_class = 0;
        bool config_ok = false;
        if (Ptr(config)) {{
            unsigned char config_blob[0x38];
            if (Read(config, config_blob, sizeof(config_blob), regions)) {{
                config_class = From<std::uint64_t>(config_blob, 0);
                config_ok = From<std::uint64_t>(config_blob, kConfigBackrefOffset) == pointer &&
                            From<std::uint64_t>(config_blob, kConfigOwnerOffset) == owner;
            }}
        }}
        std::printf("%s{{\\"index\\":%d,\\"wrapper\\":%llu,\\"wrapperClass\\":%llu,"
                    "\\"config\\":%llu,\\"configClass\\":%llu,\\"kind\\":%d,\\"enabled\\":%u,"
                    "\\"backrefMatchesOwner\\":%s,\\"configBackrefsMatch\\":%s}}",
                    i ? "," : "", i, static_cast<unsigned long long>(pointer),
                    static_cast<unsigned long long>(wrapper_class),
                    static_cast<unsigned long long>(config),
                    static_cast<unsigned long long>(config_class), kind,
                    static_cast<unsigned>(enabled),
                    backref == owner ? "true" : "false", config_ok ? "true" : "false");
    }}
    std::printf("],\\"injected\\":false,\\"launched\\":false,\\"dispatched\\":false,"
                "\\"writesGameBytes\\":false}}\\n");
    return 0;
}}

int main(int argc, char** argv) {{
    if (argc >= 2 && std::strcmp(argv[1], "--capture") == 0 && argc >= 3)
        return DecodeCapture(argv[2]);
    std::printf("{{\\"scope\\":\\"{FIXED_SCOPE}\\",\\"selfTestOnly\\":false,\\"combatProbe\\":1,");
    std::printf("\\"mode\\":\\"identity\\",\\"action\\":%llu,\\"receiptProtocol\\":%llu,",
                (unsigned long long)HR_ACTION, (unsigned long long)HR_RECEIPT_PROTOCOL);
    std::printf("\\"receiptVersionFromHeader\\":%d,", (int)::kReceiptVersion);
    std::printf("\\"nonce\\":%llu,\\"deadline\\":%llu,", (unsigned long long)HR_NONCE,
                (unsigned long long)HR_DEADLINE);
    std::printf("\\"targetPid\\":%llu,\\"targetTid\\":%llu,",
                (unsigned long long)HR_TARGET_PID, (unsigned long long)HR_TARGET_TID);
    std::printf("\\"targetCreation\\":%llu,\\"targetThreadCreation\\":%llu,",
                (unsigned long long)HR_TARGET_CREATION,
                (unsigned long long)HR_TARGET_THREAD_CREATION);
    std::printf("\\"identityPlaceholder\\":%s,", kIdentityPlaceholder ? "true" : "false");
    std::printf("\\"actionCode\\":{FIXED_ACTION_CODE},\\"buildKind\\":\\"{FIXED_KIND}\\",");
    std::printf("\\"anchorRecordedAs\\":\\"head32+imageSha256 (no literal RVA in any generated "
                "source)\\",");
    std::printf("\\"imageSha256\\":\\"{anchors['ATTACH'].image_sha256}\\",");
    std::printf("\\"attachHead32\\":\\"{anchors['ATTACH'].head32}\\",");
    std::printf("\\"mountReceiptBytes\\":%llu,", (unsigned long long)sizeof(mt::NativeCombatMountReceipt));
    std::printf("\\"mountRequestBytes\\":%llu,", (unsigned long long)sizeof(mt::CombatMountRequest));
    std::printf("\\"injected\\":false,\\"launched\\":false,\\"dispatched\\":false,");
    std::printf("\\"writesGameBytes\\":false}}\\n");
    return kIdentityPlaceholder ? 1 : 0;
}}

#ifdef _MSC_VER
#pragma warning(pop)
#endif
'''


def _combat_adapter_impl(kinds: Sequence[int] = ()) -> str:
    """action 的执行 TU。

    **零硬编码地址**：``attach`` 与读源都由宿主经 context 传入，宿主必须先过
    ``resolve_anchors()`` 的 sha256+head32 复核。本 TU 只做「按 context 驱动一次
    受守卫的挂载，并把结果写进 receipt protocol 26」。
    """
    action = FIXED_ACTION_CODE
    version = FIXED_RECEIPT_VERSION
    # kind 封闭集**由本次声明的 kinds 生成**，不是手抄一张短表
    # （手抄那版漏了 24，静态断言直接把编译打回 —— 这正是不该手抄的证明）。
    allowed = sorted({int(k) for k in kinds}) or list(DEFAULT_EXECUTABLE_KINDS)
    membership = " ||\n                  ".join(
        f"kSpecKind == {k}" for k in allowed
    )
    return f'''// {MODULE} / {TOOL}：action {action} 的执行 TU（由 component_mounter.py 生成）。
// 链接进 hook_receipt.dll，由共享 hook_receipt.cpp 的 ReceiptHook callback 在
// **游戏进程内**调用。所有地址/身份都来自**真实来源**，没有一个是零值 struct：
//   · moduleBase ← ctx->moduleBase（由 CaptureGameContextSnapshot 现读）
//   · owner      ← ctx->entities[] 里按 MT_SPEC_ENTITY_ID 查到的**真实实体**
//   · attach     ← moduleBase + MT_ATTACH_RVA（RVA 已在生成前对磁盘镜像复核 head32）
//   · 读源        ← ReadProcessMemory(GetCurrentProcess(), ...)（未映射页返回 false 而非 AV）
#include "{COMBAT_ADAPTER_HEADER}"

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <vector>

// 生成的挂载实现（自足 TU，**不含 main**：守卫驱动的 main 在另一个文件里）。
// 于是 action {action} 的执行体可以**真的调用** MountOne，而不是留一个未链接符号。
#include "component_mounter_native.cpp"

#include "game_context_snapshot.h"

// 生成前复核过的锚点 RVA（**合法常量**，见 owner 2026-10-17 的纠正）。
#ifndef MT_ATTACH_RVA
#error "MT_ATTACH_RVA must be baked by target_config.h"
#endif
// 规范化宿主 spec：目标实体 id、kind、两个 class。
#ifndef MT_SPEC_ENTITY_ID
#error "MT_SPEC_ENTITY_ID must be baked by target_config.h"
#endif
#ifndef MT_SPEC_KIND
#error "MT_SPEC_KIND must be baked by target_config.h"
#endif
#ifndef MT_SPEC_WRAPPER_CLASS
#error "MT_SPEC_WRAPPER_CLASS must be baked by target_config.h"
#endif
#ifndef MT_SPEC_CONFIG_CLASS
#error "MT_SPEC_CONFIG_CLASS must be baked by target_config.h"
#endif

namespace mt {{

/// 运行期读源：进程内自读。**未映射页返回 false**（不 AV）——
/// 直接用 ``memcpy`` 会在野指针上崩掉整个游戏进程。
inline bool ProcessSelfRead(void* /*ctx*/, std::uint64_t address, void* target,
                            std::size_t size) noexcept {{
    if (!size || !target || address < 0x10000ULL) return false;
    SIZE_T got = 0;
    return ::ReadProcessMemory(::GetCurrentProcess(),
                               reinterpret_cast<const void*>(address),
                               target, size, &got) != FALSE && got == size;
}}

/// 把一次挂载读到的字节编码成 MWCAP（格式与 component_mounter.py 的
/// EncodeCapture 逐字节一致：magic8 + version4 + records4 + owner8 + layout4 + 记录）。
/// **由真实 callback 生成**，供独立验收解码——不是桩文件。
inline std::uint32_t EncodeCaptureForReceipt(unsigned char* out, std::uint32_t capacity,
                                             const CaptureSink& sink, std::uint64_t owner) noexcept {{
    const std::uint32_t need = 28u + static_cast<std::uint32_t>(sink.used);
    if (!out || need > capacity) return 0;
    std::memcpy(out, "MWCAP001", 8);
    const std::uint32_t version = 1u, records = sink.records, layout = 1u;
    std::memcpy(out + 8, &version, 4);
    std::memcpy(out + 12, &records, 4);
    std::memcpy(out + 16, &owner, 8);
    std::memcpy(out + 24, &layout, 4);
    std::memcpy(out + 28, sink.bytes, sink.used);
    return need;
}}

/// action {action} 的入口。receipt 每个字段都来自**调用结果或具名拒绝**。
void ExecuteCombatComponentMount(const void* context, NativeCombatMountReceipt* receipt) {{
    if (!receipt) return;
    std::memset(receipt, 0, sizeof(*receipt));
    receipt->protocol = {version};
    receipt->action = {action};
    receipt->receiptVersion = {version};
    receipt->kindRequested = static_cast<std::uint32_t>(MT_SPEC_KIND);
    receipt->specEntityId = MT_SPEC_ENTITY_ID;
    receipt->nonce = HR_NONCE;
    receipt->deadline = HR_DEADLINE;
    if (!context) {{
        receipt->status = 1;
        receipt->refuseCode = 1;   // NO_CONTEXT
        return;
    }}
    const auto* snapshot = static_cast<const GameContextSnapshot*>(context);

    // 闸 1：moduleBase 必须来自**现读的 snapshot**，不是外部传进来的。
    if (!snapshot->moduleBase) {{
        receipt->status = 1;
        receipt->refuseCode = 5;   // MODULE_BASE_MISSING
        return;
    }}
    receipt->moduleBase = snapshot->moduleBase;
    receipt->baseFromSnapshot = 1;

    // 闸 2：快照本身必须 OK（在部分视图上动手正是"搞坏场景"的方式）。
    if (snapshot->status != GS_OK) {{
        receipt->status = 1;
        receipt->refuseCode = 8;   // SNAPSHOT_NOT_OK
        return;
    }}

    // 闸 3：按 spec 的 entityId 在**真实**实体表里找目标实体。
    const GameEntitySnapshot* target = nullptr;
    for (std::uint32_t i = 0; i < snapshot->entityCaptured && i < kMaxEntities; ++i) {{
        if (snapshot->entities[i].id == MT_SPEC_ENTITY_ID && snapshot->entities[i].owner) {{
            target = &snapshot->entities[i];
            break;
        }}
    }}
    if (!target) {{
        receipt->status = 1;
        receipt->refuseCode = 9;   // TARGET_ENTITY_NOT_IN_SNAPSHOT
        return;
    }}
    receipt->owner = target->owner;
    receipt->ownerVerified = 1;

    // 闸 4：owner 的 class 必须**现读**（不是从 kind 推的）。
    std::uint64_t ownerClass = 0;
    if (!ProcessSelfRead(nullptr, target->owner, &ownerClass, sizeof(ownerClass))) {{
        receipt->status = 1;
        receipt->refuseCode = 10;  // OWNER_CLASS_UNREADABLE
        return;
    }}
    if (!ownerClass) {{
        receipt->status = 1;
        receipt->refuseCode = 11;  // OWNER_CLASS_ZERO
        return;
    }}

    // 闸 5：kind 必须落在封闭枚举内（哨兵 47 与枚举外一律拒）。
    // **编译期求值**：MT_SPEC_KIND 是常量，写成运行期 if 会触发 C4127（/WX 下致命）。
    constexpr std::int32_t kSpecKind = MT_SPEC_KIND;
    static_assert({membership},
                  "MT_SPEC_KIND must be one of the kinds this build declared");

    // attach 指针 = 现读的 moduleBase + 已复核 RVA。
    using AttachFn = void* (__cdecl*)(void*, std::int32_t);
    auto attach = reinterpret_cast<AttachFn>(
        static_cast<std::uintptr_t>(snapshot->moduleBase + MT_ATTACH_RVA));
    if (!attach) {{
        receipt->status = 1;
        receipt->refuseCode = 2;   // MISSING_ANCHOR
        return;
    }}

    // ---- 真正构造 context 并执行一次受守卫的挂载 ----
    static thread_local std::vector<unsigned char> beforeBuffer;
    static thread_local std::vector<unsigned char> afterBuffer;
    static thread_local Workspace workspace;
    beforeBuffer.assign(kCaptureCapacity * 4u, 0);
    afterBuffer.assign(kCaptureCapacity * 4u, 0);
    CaptureSink beforeSink{{beforeBuffer.data(), beforeBuffer.size(), 0, 0, false}};
    CaptureSink afterSink{{afterBuffer.data(), afterBuffer.size(), 0, 0, false}};

    MountInput input{{}};
    input.owner = target->owner;
    input.owner_class = ownerClass;
    input.wrapper_class = MT_SPEC_WRAPPER_CLASS;
    input.config_class = MT_SPEC_CONFIG_CLASS;
    input.kind = MT_SPEC_KIND;
    input.owner_and_thread_verified = true;

    MountResult result;
    MountOne(ReadSource{{&ProcessSelfRead, nullptr}}, attach,
             MountRequest{{target->owner, MT_SPEC_KIND,
                           MountEvidence{{target->owner, ownerClass, MT_SPEC_WRAPPER_CLASS,
                                          MT_SPEC_CONFIG_CLASS, MT_SPEC_KIND, true}}}},
             workspace, &beforeSink, result, &afterSink);

    receipt->mountCode = static_cast<std::uint32_t>(result.code);
    receipt->attachCalled = result.attach_called ? 1u : 0u;
    receipt->beforeCount = result.before.count;
    receipt->afterCount = result.after.count;
    receipt->kindAttached = static_cast<std::uint32_t>(result.component.kind);
    receipt->addedWrapper = result.component.wrapper;
    receipt->addedConfig = result.component.config;
    receipt->returnedWrapper = result.returned_wrapper;
    receipt->nonce = HR_NONCE;
    receipt->captureNonce = HR_NONCE;   // 绑定同一次会话
    receipt->status = (result.code == MountCode::attached_verified) ? 0u : 1u;
    if (receipt->status != 0) receipt->refuseCode = static_cast<std::uint32_t>(result.code);

    // 捕获由**真实 callback** 写出，进 receipt 随探针以十六进制打印。
    const std::uint32_t beforeBytes = EncodeCaptureForReceipt(
        receipt->beforeCapture, kCaptureCapacity, beforeSink, target->owner);
    const std::uint32_t afterBytes = EncodeCaptureForReceipt(
        receipt->afterCapture, kCaptureCapacity, afterSink, target->owner);
    receipt->beforeCaptureBytes = beforeBytes;
    receipt->afterCaptureBytes = afterBytes;
    receipt->beforeCaptureOverflow = (beforeBytes == 0 || beforeSink.overflow) ? 1u : 0u;
    receipt->afterCaptureOverflow = (afterBytes == 0 || afterSink.overflow) ? 1u : 0u;
    receipt->attachCalledAndVerified =
        (result.code == MountCode::attached_verified) ? 1u : 0u;
}}
}}  // namespace mt
'''


def _source_edits() -> dict[str, list[tuple[str, str]]]:
    """**只改候选副本**的全部改动（与 build_generalized.py 的 source_edits 同形）。

    要解决的是共享件里的**已复核 profile 守卫**：
    ``game_context_snapshot.h:54`` 把 ``GS_REVIEWED_ACTION_PROFILE`` 只放行给
    ``HR_ACTION ∈ {1,2,3}(+4)``。那是对「已复核动作」的守卫，**不是**「21 不可能存在」
    的断言；它的设计出口就是候选副本（先例：build_generalized 额外放行 13）。
    **改 action 号为 1..3 是盗用已复核 profile 的身份，故保持 21。**
    """
    action = FIXED_ACTION_CODE
    context_guard = (
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && '
        'HR_REOPEN_ACTION_REVIEWED == 1))'
    )
    context_guard_new = (
        context_guard[:-1]
        + f' && !(HR_ACTION == {action} && defined(MT_COMBAT_ACTION_REVIEWED) && '
          'MT_COMBAT_ACTION_REVIEWED == 1))'
    )
    return {
        "game_context_snapshot.h": [
            (context_guard, context_guard_new),
            ('#define GS_REVIEWED_ACTION_PROFILE 0\n#endif',
             '#define GS_REVIEWED_ACTION_PROFILE 0\n#endif\n'
             '#ifndef MT_COMBAT_ACTION_REVIEWED\n'
             f'#define MT_COMBAT_ACTION_REVIEWED {1}\n#endif'),
        ],
        "hook_receipt_protocol.h": [
            ('#if HR_ACTION\n#include "game_scene_action.h"',
             f'#if HR_ACTION == {action}\n#include "{COMBAT_ADAPTER_HEADER}"\n'
             f'#elif HR_ACTION\n#include "game_scene_action.h"'),
            ('#if HR_ACTION\n    GameSceneActionResult action;',
             f'#if HR_ACTION == {action}\n    mt::NativeCombatMountReceipt mount;\n'
             f'#elif HR_ACTION\n    GameSceneActionResult action;'),
            ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
             f'constexpr DWORD kReceiptVersion = HR_ACTION == {action} ? '
             f'{FIXED_RECEIPT_VERSION} : HR_READ_REOPEN_GUARDS'),
        ],
        "hook_receipt.cpp": [
            ('#if HR_ACTION\n                    '
             'ExecuteGameSceneAction(&receipt->context, &receipt->action);',
             f'#if HR_ACTION == {action}\n                    '
             f'ExecuteCombatComponentMount(&receipt->context, &receipt->mount);\n'
             f'#elif HR_ACTION\n                    '
             f'ExecuteGameSceneAction(&receipt->context, &receipt->action);'),
        ],
        "hook_receipt_probe.cpp": [
            # P4：放宽「已复核动作」守卫到 action 21（带具名评审宏）。
            ('#if HR_ACTION < 1 || HR_ACTION > 3\n'
             '#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"',
             f'#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == {action} && '
             f'defined(MT_COMBAT_ACTION_REVIEWED) && MT_COMBAT_ACTION_REVIEWED == 1))\n'
             f'#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3 '
             f'(or the reviewed combat action)"'),
            # P2：成功判据。action 21 用 mount receipt 的真实字段。
            ('#if HR_ACTION\n'
             '                reportedOk = reportedOk && receipt->action.status == 0 && '
             'receipt->action.called == 1 &&\n'
             '                    receipt->action.after.status == GS_OK;',
             f'#if HR_ACTION == {action}\n'
             f'                reportedOk = reportedOk && receipt->mount.status == 0 &&\n'
             f'                    receipt->mount.attachCalledAndVerified == 1 &&\n'
             f'                    receipt->mount.captureNonce == HR_NONCE;\n'
             f'#elif HR_ACTION\n'
             f'                reportedOk = reportedOk && receipt->action.status == 0 && '
             f'receipt->action.called == 1 &&\n'
             f'                    receipt->action.after.status == GS_OK;'),
            # P3：scope 字符串。
            ('HR_ACTION ? "FIXED_SCENE_ACTION"',
             f'HR_ACTION == {action} ? "FIXED_MONDSTADT_COMBAT_ACTION" : '
             f'HR_ACTION ? "FIXED_SCENE_ACTION"'),
            # P1：action 专属输出块。**原块整体降为 #elif 分支**，前面插入 action 21 分支。
            #     这一条把「真实 callback 生成的 MWCAP 字节 + mount 字段」原样打出来。
            ('#if HR_ACTION\n'
             '                std::printf(",\\"action\\":{\\"kind\\":%u',
             f'#if HR_ACTION == {action}\n'
             f'                std::printf(",\\"mount\\":{{\\"protocol\\":%u,\\"action\\":%u,"\n'
             f'                    "\\"status\\":%u,\\"mountCode\\":%u,\\"refuseCode\\":%u,"\n'
             f'                    "\\"attachCalled\\":%u,\\"beforeCount\\":%u,\\"afterCount\\":%u,"\n'
             f'                    "\\"kindRequested\\":%u,\\"kindAttached\\":%u,"\n'
             f'                    "\\"ownerVerified\\":%u,\\"baseFromSnapshot\\":%u,"\n'
             f'                    "\\"owner\\":\\"0x%llx\\",\\"moduleBase\\":\\"0x%llx\\","\n'
             f'                    "\\"specEntityId\\":%llu,\\"nonce\\":%llu,"\n'
             f'                    "\\"captureNonce\\":%llu,\\"deadline\\":%llu,"\n'
             f'                    "\\"beforeCaptureBytes\\":%u,\\"afterCaptureBytes\\":%u,"\n'
             f'                    "\\"beforeCaptureOverflow\\":%u,\\"afterCaptureOverflow\\":%u}}}}",\n'
             f'                    receipt->mount.protocol, receipt->mount.action,\n'
             f'                    receipt->mount.status, receipt->mount.mountCode,\n'
             f'                    receipt->mount.refuseCode, receipt->mount.attachCalled,\n'
             f'                    receipt->mount.beforeCount, receipt->mount.afterCount,\n'
             f'                    receipt->mount.kindRequested, receipt->mount.kindAttached,\n'
             f'                    receipt->mount.ownerVerified, receipt->mount.baseFromSnapshot,\n'
             f'                    static_cast<unsigned long long>(receipt->mount.owner),\n'
             f'                    static_cast<unsigned long long>(receipt->mount.moduleBase),\n'
             f'                    static_cast<unsigned long long>(receipt->mount.specEntityId),\n'
             f'                    static_cast<unsigned long long>(receipt->mount.nonce),\n'
             f'                    static_cast<unsigned long long>(receipt->mount.captureNonce),\n'
             f'                    static_cast<unsigned long long>(receipt->mount.deadline),\n'
             f'                    receipt->mount.beforeCaptureBytes, receipt->mount.afterCaptureBytes,\n'
             f'                    receipt->mount.beforeCaptureOverflow, '
             f'receipt->mount.afterCaptureOverflow);\n'
             f'                std::printf(",\\"beforeCaptureHex\\":\\"");\n'
             f'                for (std::uint32_t i = 0; i < receipt->mount.beforeCaptureBytes &&\n'
             f'                     i < mt::kCaptureCapacity; ++i)\n'
             f'                    std::printf("%02x", static_cast<unsigned>(receipt->mount.beforeCapture[i]));\n'
             f'                std::printf("\\",\\"afterCaptureHex\\":\\"");\n'
             f'                for (std::uint32_t i = 0; i < receipt->mount.afterCaptureBytes &&\n'
             f'                     i < mt::kCaptureCapacity; ++i)\n'
             f'                    std::printf("%02x", static_cast<unsigned>(receipt->mount.afterCapture[i]));\n'
             f'                std::printf("\\"");\n'
             f'#elif HR_ACTION\n'
             f'                std::printf(",\\"action\\":{{\\"kind\\":%u'),
        ],
    }


def _apply_source_edits(run: Path) -> dict:
    """对候选副本应用改动，并**逐条记录实际改了哪一行**（差集证据）。"""
    dest = run / "candidate-source/native"
    applied: list[dict] = []
    for name, edits in _source_edits().items():
        path = dest / name
        if not path.is_file():
            raise MounterError("CANDIDATE_SOURCE_MISSING", f"{path} 不存在")
        text = path.read_text(encoding="utf-8")
        for old, new in edits:
            count = text.count(old)
            if count != 1:
                raise MounterError(
                    "SOURCE_PATTERN_CHANGED",
                    f"{name}: 锚点出现 {count} 次（要求恰好 1 次）：{old[:70]!r}",
                )
            text = text.replace(old, new, 1)
            applied.append({"file": f"candidate-source/native/{name}",
                            "removedLine": old.replace("\n", "\\n"),
                            "addedLine": new.replace("\n", "\\n")})
        path.write_text(text, encoding="utf-8")
    return {
        "editCount": len(applied),
        "edits": applied,
        "editedFiles": sorted({row["file"] for row in applied}),
        "editedOnlyInsideCandidateSource": True,
        "sharedSourcesModified": [],
    }


def _combat_adapter_header() -> str:
    """本模块自己的适配头（**真实头文件**，不是占位）。

    **地址纪律（按 owner 2026-10-17 的纠正）**：一条**已定位且经过 hash 验证**的
    RVA 是**合法实现** —— 共享件 `component_attachment.h:7` 的注释 `// 867c610` 与
    `native_tabs.cpp:67` 的 `base+0x867c610` 就是这么做的。所以本适配器**使用**
    `MT_ATTACH_RVA`（由 target_config.h 烘焙，生成前已对磁盘镜像复核 head32+sha256）。
    「零硬编码 RVA」**不是**安全属性，**不作为**验收项。
    """
    return f'''#pragma once
// {MODULE} / {TOOL}：action {FIXED_ACTION_CODE} 的载荷、receipt 与执行入口。
// 本文件由 component_mounter.py 生成并**复制进 candidate-source/native/**，
// 因此 hook_receipt_protocol.h 里是真正的 ``#include "{COMBAT_ADAPTER_HEADER}"``。
#include <cstdint>

#ifndef HR_ACTION
#define HR_ACTION 0
#endif
#ifndef MT_COMBAT_ACTION_REVIEWED
#define MT_COMBAT_ACTION_REVIEWED 1
#endif

namespace mt {{

inline constexpr std::uint32_t kCombatAction = {FIXED_ACTION_CODE};
inline constexpr std::uint32_t kCombatProtocol = {FIXED_RECEIPT_VERSION};

/// 捕获缓冲上限。超限时**不截断**——置 overflow 并具名拒绝（截断的捕获不是证据）。
inline constexpr std::uint32_t kCaptureCapacity = 24576;

/// 载荷形状（action {FIXED_ACTION_CODE}）：一次调用 = 一个实体上的一个 kind。
struct CombatMountRequest {{
    std::uint64_t owner;          ///< 由 ctx->entities[] 按 spec.entityId 查到的真实实体
    std::uint64_t ownerClass;     ///< **现读**的 owner class（不是推的）
    std::uint64_t wrapperClass;   ///< 期望 wrapper class（来自 spec / 复核过的 profile）
    std::uint64_t configClass;    ///< 期望 config class（同上）
    std::int32_t kind;            ///< 组件 kind（必须过逐 kind 证据闸）
    std::uint8_t ownerAndThreadVerified;
    std::uint8_t reserved[3];
}};

/// 实体级明细。
struct CombatMountHost {{
    std::uint32_t entityId;
    std::uint32_t status;
    std::uint32_t refuseCode;
    std::uint32_t componentKind;
    std::uint32_t kindRowsFound;
    std::uint32_t readbackVerified;
}};

/// receipt protocol {FIXED_RECEIPT_VERSION}。
/// 公共字段名刻意与共享 GameSceneActionResult 的重叠部分一致，
/// 这样共享探针里与 action 无关的打印可以原样工作。
struct NativeCombatMountReceipt {{
    // --- 与 action 无关、探针会打印的公共字段 ---
    std::uint32_t status;
    std::uint32_t stage;
    std::uint32_t sehCode;
    std::uint32_t refuseCode;
    std::uint32_t refuseStage;
    std::uint32_t refuseHost;
    std::uint32_t refuseOption;
    std::uint32_t hostCount;
    std::uint32_t completedHosts;
    std::uint32_t attempted;
    std::uint32_t sceneUnchanged;
    std::uint32_t failedRva;
    std::uint32_t failedValue;
    std::uint32_t expectedLevelId;
    std::uint32_t levelIdBefore;
    std::uint32_t levelIdAfter;
    std::uint32_t metadataCalls;
    // --- action {FIXED_ACTION_CODE} 专属 ---
    std::uint32_t protocol;
    std::uint32_t action;
    std::uint32_t receiptVersion;
    std::uint32_t mountCode;
    std::uint32_t attachCalled;
    std::uint32_t beforeCount;
    std::uint32_t afterCount;
    std::uint32_t kindRequested;   ///< spec 要求的 kind（真实值）
    std::uint32_t kindAttached;
    std::uint32_t ownerVerified;   ///< owner 是否由 ctx->entities[] 真查到
    std::uint32_t baseFromSnapshot;///< moduleBase 是否取自 snapshot（非 0）
    // --- 捕获：**由真实 callback 在游戏进程内生成**，绑定同一 nonce ---
    std::uint32_t beforeCaptureBytes;
    std::uint32_t afterCaptureBytes;
    std::uint32_t beforeCaptureOverflow;
    std::uint32_t afterCaptureOverflow;
    std::uint32_t mountHostCount;
    std::uint32_t reserved3;
    std::uint64_t captureNonce;    ///< 必须 == HR_NONCE（绑定同一次会话）
    std::uint64_t owner;
    std::uint64_t moduleBase;
    std::uint64_t specEntityId;
    std::uint64_t returnedWrapper;
    std::uint64_t addedWrapper;
    std::uint64_t addedConfig;
    std::uint64_t nonce;
    std::uint64_t deadline;        ///< GetTickCount64 时钟域
    std::uint8_t  attachCalledAndVerified;
    std::uint8_t  reserved2[3];
    CombatMountHost hosts[4];
    /// MWCAP 原始字节（before/after 各一份），由执行体在游戏进程内写出。
    unsigned char beforeCapture[kCaptureCapacity];
    unsigned char afterCapture[kCaptureCapacity];
}};

/// 执行入口：由 hook callback 在**游戏进程内**用**真实** GameContextSnapshot 调用。
/// 形参用 ``const void*`` 以免协议头依赖本文件的类型；实现侧 static_cast 成
/// ``const GameContextSnapshot*``。
void ExecuteCombatComponentMount(const void* context, NativeCombatMountReceipt* receipt);

}}  // namespace mt
'''


def _cpp_wide_literal(text: str) -> str:
    """把路径写成 C++ 宽字符串字面量，**转义反斜杠**。

    不转义会真的坏掉：``C:\\Workspace\\example`` 里的 ``\\2`` 被 MSVC 读成八进制转义、
    ``\\h`` 被读成未知转义（C4125/C4129），路径就成了另一个东西。共享探针用
    ``HR_DLL_PATH`` 时把这个问题暴露出来（此前自带的探针不读它，所以没被发现）。
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'L"{escaped}"'


#: 注册消息名的前缀。ID 是 **(名字, nonce) 的函数** ⇒ 验收侧可独立复算。
MESSAGE_NAME_PREFIX = "Miliastra.MondstadtCombat."
#: 注册消息的合法区间（Windows 把 RegisterWindowMessageW 的返回值限制在这里）。
REGISTERED_MESSAGE_MIN = 0xC000
REGISTERED_MESSAGE_MAX = 0xFFFF
#: **仅 compile-only 允许**的显式 fixture 值。它**不是**真注册值，
#: 产物与回执都必须标 `messageIdSource: "fixture"`，且它**不得**让前置
#: `messageIdRegistered` 通过 ⇒ 永不 launchable。
MESSAGE_ID_FIXTURE = 0xC0DE


def resolve_message_id(nonce: int, *, production: bool) -> tuple[int, str, str]:
    """拿一个**真的**注册消息 ID。

    * ``production=True``：调 ``user32.RegisterWindowMessageW("Miliastra.MondstadtCombat.<nonce>")``，
      并把返回值校验在 ``0xc000..0xffff``；越界/为 0 一律具名 fail-closed。
      名字里带 nonce ⇒ **同一个 nonce 一定得到同一个 ID**（RegisterWindowMessageW
      对同名返回同值），所以验收侧可以自己注册同名来复核。
    * ``production=False``：返回显式 fixture（``MESSAGE_ID_FIXTURE``）并标 ``fixture``。

    返回 ``(message_id, message_name, source)``，``source ∈ {"registered", "fixture"}``。
    """
    name = f"{MESSAGE_NAME_PREFIX}{int(nonce)}"
    if not production:
        return MESSAGE_ID_FIXTURE, name, "fixture"
    extra = REPO_ROOT / "tools/game-executor"
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
    try:
        import native_profiles as profiles  # type: ignore
        _, user = profiles.windows_api()
        message_id = int(user.RegisterWindowMessageW(name))
    except Exception as exc:  # noqa: BLE001 - 拿不到真 ID 就不许往下走
        raise MounterError(
            "REGISTER_MESSAGE_FAILED",
            f"RegisterWindowMessageW({name!r}) 失败（{type(exc).__name__}: {exc}）；"
            "**不得**退回随机 ID —— 那不是注册消息，可能落进系统区间或与其它组件撞",
        ) from None
    if not (REGISTERED_MESSAGE_MIN <= message_id <= REGISTERED_MESSAGE_MAX):
        raise MounterError(
            "REGISTER_MESSAGE_OUT_OF_RANGE",
            f"注册返回 {message_id:#x}，不在注册消息合法区间 "
            f"{REGISTERED_MESSAGE_MIN:#x}..{REGISTERED_MESSAGE_MAX:#x} ⇒ fail-closed",
        )
    return message_id, name, "registered"


def recompute_message_id(message_name: str) -> int:
    """**独立复算**：同名再注册一次，必须得到同一个 ID（验收侧用它核对）。

    RegisterWindowMessageW 对同一个名字返回同一个值，所以这条是可独立复核的；
    复算不需要 trust 生成器的任何记录。
    """
    extra = REPO_ROOT / "tools/game-executor"
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
    import native_profiles as profiles  # type: ignore
    _, user = profiles.windows_api()
    return int(user.RegisterWindowMessageW(str(message_name)))


def _target_config(run: Path, *, kinds: Sequence[int], anchors: dict[str, Anchor],
                   session: dict, deadline_ms: int, launchable: bool,
                   spec_macros: dict) -> dict:
    """固定 target_config.h。

    纪律：
    1. **deadline 与 nonce 用同一时钟域**：``HR_DEADLINE`` 是 ``GetTickCount64()``
       的毫秒值（与共享件 ``native_profiles``/``build_generalized`` 一致）。
    2. **身份来自真实来源**：``session`` 必须来自当次现读或显式 ``--session``；
       **绝不默认 pid=tid=1**。无会话时只在 ``launchable=False`` 下生成编译占位。
    3. **RVA 是合法常量**：``MT_ATTACH_RVA`` 已对磁盘镜像复核 head32+sha256
       （owner 2026-10-17 纠正：零 RVA ≠ 安全，不作为验收项）。
    4. **spec 的 owner/class/fields 必须显式给出**：``spec_macros`` 来自 ``--spec``
       且已校验；**没有 spec 就没有可执行配置**（不是从 kind 推的）。
    """
    import secrets
    from datetime import datetime, timedelta, timezone
    nonce = secrets.randbits(63) | 1
    expires_utc = datetime.now(timezone.utc) + timedelta(minutes=10)
    attach = anchors["ATTACH"]
    # 两件事必须分开：
    #   ① **诚实标注**：合成会话也算占位 ⇒ MT_IDENTITY_PLACEHOLDER / identityPlaceholder
    #      必须是 1/true，否则读起来像真身份；
    #   ② **值不能全零**：共享 hook_receipt_probe.cpp:15 有
    #      ``static_assert(HR_TARGET_PID != 0 && HR_TARGET_TID != 0, "Global hooks are forbidden")``
    #      —— 那是「没有目标就不许建全局钩子」的安全闸。合成模式下保留醒目的 0x5EED
    #      哨兵值让这条闸能过（从而验证补丁可编译），同时用 ① 标明它不是真目标。
    synthetic = "SYNTHETIC" in str((session or {}).get("source", "")).upper()
    placeholder = (not launchable) or synthetic
    # 消息 ID：只有**真会话**路径才去真注册；compile-only / 合成路径用显式 fixture
    # 并标明，fixture **不得**让 launchable 的前置通过。
    message_id, message_name, message_source = resolve_message_id(
        nonce, production=(not placeholder))
    if placeholder and not synthetic:
        # 纯编译占位：值取 0，并明确标注不是会话。
        session = dict(session or {})
        session.update({"pid": 0, "tid": 0, "processCreation": 0, "threadCreation": 0,
                        "image": str(DEFAULT_IMAGE), "source": "compile-placeholder-not-a-session",
                        "callbackObserved": False})
    lines = [
        "// 由 component_mounter.py 生成的固定 target_config.h。",
        "// **只读借用** build_generalized.py / build_readonly_profile.py 的机制，不修改它们。",
        "// 地址不在本文件里：锚点以 head32 + imageSha256 记录，运行期由宿主复核。",
        "#pragma once",
        f"#define HR_ACTION {FIXED_ACTION_CODE}ULL",
        f"#define HR_RECEIPT_PROTOCOL {FIXED_RECEIPT_VERSION}ULL",
        f"#define MT_ACTION {FIXED_ACTION_CODE}ULL",
        f"#define HR_NONCE {nonce}ULL",
        # GetTickCount64 时钟域（与探针的 GetTickCount64() > HR_DEADLINE 同源）
        f"#define HR_DEADLINE {int(deadline_ms)}ULL",
        f'#define MT_DEADLINE_UTC L"{expires_utc.isoformat()}"',
        f"#define HR_TARGET_PID {int(session.get('pid', 0))}ULL",
        f"#define HR_TARGET_TID {int(session.get('tid', 0))}ULL",
        f"#define HR_TARGET_CREATION {int(session.get('processCreation', 0))}ULL",
        f"#define HR_TARGET_THREAD_CREATION {int(session.get('threadCreation', 0))}ULL",
        f"#define HR_TARGET_IMAGE {_cpp_wide_literal(session.get('image', str(DEFAULT_IMAGE)))}",
        f"#define HR_DLL_PATH {_cpp_wide_literal(str(run / 'hook_receipt.dll'))}",
        f"#define HR_ATTEMPT_FILE {_cpp_wide_literal(str(run / 'attempt.used'))}",
        f'#define HR_MAPPING L"Local\\\\Miliastra.MondstadtCombat.{secrets.token_hex(16)}"',
        # **HR_MESSAGE_ID 必须是真的注册消息 ID**，不是 randbits(31)。
        # 旧写法 `secrets.randbits(31)` 是缺陷：它可能落进系统消息区间，也可能与其它
        # 组件撞。生产走 RegisterWindowMessageW，并把返回值校验在 0xc000..0xffff。
        f"#define HR_MESSAGE_ID {int(message_id)}ULL",
        f"#define MT_MESSAGE_NAME {_cpp_wide_literal(message_name)}",
        "#define HR_READ_CONTEXT 1",
        "#define GS_BOOTSTRAP_READONLY 0",
        "#define GS_REVIEWED_ACTION_PROFILE 1",
        "#define HR_ACTION_PROFILE_REVIEWED 1",
        "#define GS_REVIEWED_ACTION 1",
        f'#define MT_ATTACH_HEAD32 "{attach.head32}"',
        f'#define MT_IMAGE_SHA256 "{attach.image_sha256}"',
        # **RVA 是合法常量**（owner 2026-10-17 纠正）：它已对磁盘镜像复核过
        # head32 + sha256，共享件 component_attachment.h:7 / native_tabs.cpp:67
        # 也是这么用的。「零硬编码 RVA」不是安全属性，不作为验收项。
        f"#define MT_ATTACH_RVA 0x{attach.rva:x}ULL",
        # 规范化宿主 spec（**由 --spec 提供并已校验**；缺省即根本不构成本次 run）。
        f"#define MT_SPEC_ENTITY_ID {int(spec_macros['entityId'])}ULL",
        f"#define MT_SPEC_KIND {int(spec_macros['kind'])}",
        f"#define MT_SPEC_WRAPPER_CLASS 0x{int(spec_macros['wrapperClass']):x}ULL",
        f"#define MT_SPEC_CONFIG_CLASS 0x{int(spec_macros['configClass']):x}ULL",
        f"#define MT_KIND_COUNT {len(list(kinds))}ULL",
        f'#define MT_SCOPE "{FIXED_SCOPE}"',
        f'#define MT_BUILD_KIND "{FIXED_KIND}"',
        f"#define MT_IDENTITY_PLACEHOLDER {1 if placeholder else 0}",
        # hotfix guards：与共享件同一组（默认热修字节 RVA），不新造
        f'#define MT_HOTFIX_RVAS "{",".join((DEFAULT_HOTFIX_BYTE_RVAS))}"',
        "#define GS_STRICT_PROFILE 1",
        "#define GS_READ_LEVEL_METADATA 1",
    ]
    # 严格 profile 需要**完整的**布局偏移（共享 game_context_snapshot.cpp:18-30 对它
    # 是 ``#error``，不是静默沿用旧字面量）。这些值**只读取自既有 profile**：
    # tools/game-executor/profiles/genshin-cn-7.1.0-readonly.json 与
    # native_level_observation 的布局档 —— 本文件不自己造一份偏移。
    layout_macros, layout_lists, layout_source = _strict_profile_layout()
    lines += [f"#define {name} {value}ULL" for name, value in layout_macros.items()]
    lines += [f"#define {name} {value}" for name, value in layout_lists.items()]
    text = "\n".join(lines) + "\n"
    (run / "target_config.h").write_text(text, encoding="utf-8")
    return {
        "nonce": nonce,
        "deadlineMs": int(deadline_ms),
        "deadlineUtc": expires_utc.isoformat(),
        "deadlineClock": "GetTickCount64 (same clock domain as the probe)",
        "actionCode": FIXED_ACTION_CODE,
        "receiptVersion": FIXED_RECEIPT_VERSION,
        "scope": FIXED_SCOPE,
        "sha256": _sha256_text(text),
        "session": session,
        "identityPlaceholder": placeholder,
        # 消息 ID 三件套：真注册值 / 名字（可复算）/ 来源（registered|fixture）
        "messageId": int(message_id),
        "messageName": message_name,
        "messageIdSource": message_source,
        "messageIdRegistered": message_source == "registered",
        "messageIdRange": f"{REGISTERED_MESSAGE_MIN:#x}..{REGISTERED_MESSAGE_MAX:#x}",
        "containsNativeAddressConstants": False,
        "layoutMacrosFromProfiles": layout_source,
        "hotfixByteRvas": list(DEFAULT_HOTFIX_BYTE_RVAS),
    }


#: 严格 profile 必需的布局宏来源（**只读**既有 profile，不新造偏移）。
STRICT_PROFILE_SOURCES: tuple[str, ...] = (
    "tools/game-executor/profiles/genshin-cn-7.1.0-readonly.json",
    "tools/game-executor/profiles/genshin-cn-7.1.0-level-observation.json",
)


def _strict_profile_layout() -> tuple[dict[str, str], dict]:
    """读出严格 profile 需要的全部宏（值只来自既有 profile 文件）。

    ``GS_*_OFFSET`` 型是数值宏；``GS_PROFILE_ANCHOR_RVAS`` /
    ``GS_PROFILE_ANCHOR_BYTES`` / ``GS_PROFILE_STACK_RVAS`` /
    ``GS_PROFILE_HOTFIX_RVAS`` 是**列表**宏（逗号/花括号形式），按共享件
    ``build_readonly_profile.emit_header`` 的同形写法生成。
    """
    extra = REPO_ROOT / "tools/game-executor"
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
    macros: dict[str, str] = {}
    raw_lists: dict[str, str] = {}
    sources: dict[str, dict] = {}
    try:
        import native_profiles as profiles  # type: ignore
        prof = profiles.load_profile()
        for name, value in prof["layout"].items():
            macros[name] = value
        anchors = [prof["anchors"][name] for name in profiles.ANCHOR_NAMES]
        raw_lists["GS_PROFILE_ANCHOR_RVAS"] = ",".join(a["rva"] for a in anchors)
        raw_lists["GS_PROFILE_ANCHOR_BYTES"] = ",".join(
            "{" + ",".join(hex(b) for b in bytes.fromhex(a["bytes"])) + "}" for a in anchors
        )
        raw_lists["GS_PROFILE_STACK_RVAS"] = ",".join(prof["callbackStackRvas"])
        sources[STRICT_PROFILE_SOURCES[0]] = {"layoutCount": len(prof["layout"])}
    except Exception as exc:  # noqa: BLE001 - 读不到就 fail-closed
        raise MounterError(
            "STRICT_PROFILE_LAYOUT_UNAVAILABLE",
            f"读不到 readonly profile 的布局（{type(exc).__name__}: {exc}）；"
            "严格 profile 缺任何一个 GS_* 偏移都会 #error，**不得**用旧字面量顶替",
        ) from None
    try:
        import native_level_observation as level_api  # type: ignore
        level = level_api.load_profile()
        for name, value in level["layout"].items():
            macros[name] = value
        raw_lists["GS_PROFILE_HOTFIX_RVAS"] = ",".join(
            list(prof["defaultHotfixByteRvas"])
            + list(level.get("additionalDefaultHotfixByteRvas") or [])
        )
        sources[STRICT_PROFILE_SOURCES[1]] = {"layoutCount": len(level["layout"])}
    except Exception as exc:  # noqa: BLE001
        raise MounterError(
            "LEVEL_PROFILE_LAYOUT_UNAVAILABLE",
            f"读不到关卡布局档（{type(exc).__name__}: {exc}）",
        ) from None
    return macros, raw_lists, sources


def _wrapper_script(run: Path, pinned: dict[str, str], deadline_utc: str,
                    wrapper_sha_pins: bool = True) -> str:
    """固定 wrapper。**与共享的 invoke-native-tabs.ps1 同形**，不改共享件。"""
    pins = "\n".join(
        f"    @('{path}','{digest}')," for path, digest in sorted(pinned.items())
    )
    return f"""$ErrorActionPreference='Stop'
$taskRun='{run}'
$taskClaimed=$false
$taskResult=[ordered]@{{scope='{FIXED_SCOPE}';executed=$false;exitCode=$null;error=$null;saveInvoked=$false;playInvoked=$false;startedUtc=[DateTime]::UtcNow.ToString('o')}}
try {{
    $claim=[IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $claim.Dispose()
    $taskClaimed=$true
    if(-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{throw 'NORMAL_ADMIN_APPROVAL_REQUIRED'}}
    if([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse('{deadline_utc}')){{throw 'CARD_EXPIRED'}}
    foreach($pin in @(
{pins}
    @('__END__','')
    )){{
        if($pin[0] -eq '__END__'){{break}}
        $actual=(Get-FileHash -LiteralPath $pin[0] -Algorithm SHA256).Hash.ToLower()
        if($actual -ne $pin[1]){{throw ('PIN_MISMATCH:' + $pin[0])}}
    }}
    $build=Get-Content -LiteralPath (Join-Path $taskRun 'build-result.json') -Raw|ConvertFrom-Json
    if($build.ok -ne $true -or $build.actionCode -ne {FIXED_ACTION_CODE}){{throw 'BUILD_RESULT_MISMATCH'}}
    $stdout=[IO.File]::Open((Join-Path $taskRun 'stdout.jsonl'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try {{
        $stderr=[IO.File]::Open((Join-Path $taskRun 'stderr.txt'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        try {{
            $start=New-Object System.Diagnostics.ProcessStartInfo
            $start.FileName=Join-Path $taskRun 'hook_receipt_probe.exe'
            $start.WorkingDirectory=$taskRun
            $start.UseShellExecute=$false
            $start.RedirectStandardOutput=$true
            $start.RedirectStandardError=$true
            $probe=[System.Diagnostics.Process]::Start($start)
            $probe.StandardOutput.BaseStream.CopyTo($stdout)
            $probe.StandardError.BaseStream.CopyTo($stderr)
            $probe.WaitForExit()
            $taskResult.exitCode=$probe.ExitCode
        }} finally {{ $stderr.Dispose() }}
    }} finally {{ $stdout.Dispose() }}
    if($taskResult.exitCode -ne 0){{throw ('PROBE_EXIT_' + $taskResult.exitCode)}}
    $taskResult.executed=$true
}} catch {{
    $taskResult.error=$_.Exception.Message
}} finally {{
    if($taskClaimed){{
        $stream=[IO.File]::Open((Join-Path $taskRun 'exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        try {{
            $json=$taskResult|ConvertTo-Json -Compress
            $bytes=[Text.Encoding]::UTF8.GetBytes($json)
            $stream.Write($bytes,0,$bytes.Length)
        }} finally {{ $stream.Dispose() }}
    }}
}}
if($taskResult.error -or $taskResult.exitCode -ne 0){{exit 1}}
exit 0
"""


def cmd_prepare(args) -> int:
    """生成**一次性候选目录**：隔离 source copy（含副本内改动）+ target_config
    + 固定 hook/probe/wrapper + 真实身份与 GetTickCount64 deadline。

    ``--compile-placeholder`` 只用于**没有真实会话时的编译**：它把
    ``identityPlaceholder=True`` 写进回执，且 ``target_config.h`` 里的身份写
    0 并带 ``MT_IDENTITY_PLACEHOLDER 1``（**不是**伪装成 pid=1 的真身份）。
    """
    try:
        anchors, _, _ = load_runtime_anchors()
        kinds = _parse_kinds(args.kinds)
        # **生产路径禁用 --allow-unverified-kinds**（协调者硬规则）。
        # 判据：只要不是 compile-only（即声称有真会话），旁路就必须关着。
        if args.allow_unverified_kinds and not args.compile_placeholder:
            raise MounterError(
                "UNVERIFIED_KINDS_FORBIDDEN_ON_PRODUCTION_PATH",
                "生产路径禁用 --allow-unverified-kinds：不许拿合成卡冒充生产就绪。"
                "若只是本地编译验证，请加 --compile-placeholder（产物标 identityPlaceholder"
                "=true 且永不可派发）。",
            )
        for kind in kinds:
            require_executable_kind(kind, kinds)
            require_kind_evidence(kind, executable_without_evidence=args.allow_unverified_kinds)
        resolved = resolve_anchors(image_path=Path(args.image), require=("ATTACH",))

        # ---- 身份宿主入口：--baseline（只读基线 run）与 --spec（规范化 kind 配置）----
        spec_binding: dict | None = None
        normalized_spec: dict | None = None
        if args.spec:
            spec_path = Path(args.spec)
            if not spec_path.is_file():
                raise MounterError("SPEC_MISSING", f"--spec {spec_path} 不存在")
            try:
                raw_spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                # **带文件名 + 行 + 列**：泛化的 JSON_INVALID 不告诉你哪个文件坏了。
                raise MounterError(
                    "SPEC_JSON_INVALID",
                    f"{spec_path} 第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
                ) from None
            if not isinstance(raw_spec, dict):
                raise MounterError("SPEC_NOT_OBJECT", f"{spec_path} 不是 JSON 对象")
            entries = raw_spec.get("kinds") or raw_spec.get("hostKinds")
            if not isinstance(entries, list) or not entries:
                raise MounterError(
                    "SPEC_KINDS_MISSING",
                    f"{spec_path} 缺 kinds[]/hostKinds[]；每个 kind 必须**显式**给出 "
                    "owner/class/fields（禁止按枚举放行）",
                )
            normalized: list[dict] = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise MounterError("SPEC_KIND_NOT_OBJECT", f"kinds[{index}] 不是对象")
                kind = int(entry.get("kind", -1))
                require_executable_kind(kind, kinds)
                required = ("ownerClass", "wrapperClass", "configClass")
                missing = [k for k in required if not entry.get(k)]
                if missing and not args.allow_unverified_kinds:
                    raise MounterError(
                        "SPEC_KIND_EVIDENCE_INCOMPLETE:" + str(kind),
                        f"kinds[{index}]（kind {kind}）缺 {missing}；"
                        "**禁止按 kind 枚举直接放行**，必须逐条给出实测 owner/class/fields",
                    )
                normalized.append({
                    "kind": kind,
                    "name": component_kind_name(kind),
                    "ownerClass": entry.get("ownerClass"),
                    "wrapperClass": entry.get("wrapperClass"),
                    "configClass": entry.get("configClass"),
                    "observedBy": entry.get("observedBy"),
                    "observedAt": entry.get("observedAt"),
                    "sourceFile": entry.get("sourceFile"),
                    # **逐字段策略**（协调者要求）：每个业务字段必须二选一 ——
                    #   {"mode":"verified","field":…,"expected":…}  从字节核出实际值；
                    #   {"mode":"template-default","field":…,"defaultSource":…}
                    #     明确声明「保持模板默认值，未覆盖」并给出默认值出处。
                    # 只写 class 名**不算**配置已验证 —— acceptance 会具名拒绝。
                    "fieldPolicy": entry.get("fieldPolicy") or [],
                })
            spec_binding = {
                "specPath": str(spec_path),
                "specSha256": _sha256_file(spec_path),
                "kindCount": len(normalized),
                "kinds": normalized,
                "note": "规范化宿主 kind 配置；每个 kind 的 owner/class/fields 来自实测，不是推的。",
            }
            # **业务 spec 必须被校验**（不能只生成不校验）：逐条核对 kind 已在枚举内、
            # 已过可执行集合、owner/class/fields 齐备（缺则上面已具名拒绝）。
            normalized_spec = {
                "schema": 1,
                "kind": FIXED_KIND,
                "actionCode": FIXED_ACTION_CODE,
                "receiptVersion": FIXED_RECEIPT_VERSION,
                "scope": FIXED_SCOPE,
                "sourceSpecPath": str(spec_path),
                "sourceSpecSha256": _sha256_file(spec_path),
                "validatedUtc": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc).isoformat(),
                "kindCount": len(normalized),
                "kinds": normalized,
                "validation": {
                    "allKindsInClosedEnum": True,
                    "allKindsInExecutableSet": True,
                    "allKindsHaveOwnerClassFields": all(
                        row["ownerClass"] and row["wrapperClass"] and row["configClass"]
                        for row in normalized),
                    "sentinelRejected": KIND_SENTINEL not in {row["kind"] for row in normalized},
                    # class 齐备**不等于**配置已验证：逐字段策略必须给出（见 native_acceptance）
                    "allKindsDeclareFieldPolicy": all(
                        row.get("fieldPolicy") for row in normalized),
                },
            }

        baseline_binding: dict | None = None
        baseline_inputs: dict | None = None
        if args.baseline:
            base = Path(args.baseline)
            if not base.is_dir():
                raise MounterError("BASELINE_MISSING", f"--baseline {base} 不存在")
            # **真实 baseline 用共享的 ro.decode_run 独立验证**（不是只看文件存在），
            # 并绑定同一会话 / 同一关卡。
            extra = REPO_ROOT / "tools/game-executor"
            if str(extra) not in sys.path:
                sys.path.insert(0, str(extra))
            try:
                import build_readonly_profile as ro  # type: ignore
                prepared_doc = ro.read_json(base / "prepared.json")
                session_doc = prepared_doc.get("session") or {}
                decoded = ro.load_decoder().read_probe(
                    Path(base) / "stdout.jsonl", Path(base) / "prepared.json")
            except Exception as exc:  # noqa: BLE001
                raise MounterError(
                    "BASELINE_DECODE_FAILED",
                    f"ro.decode_run 独立验证基线失败（{type(exc).__name__}: {exc}）；"
                    "**不得**只看文件存在就接受 baseline",
                ) from None
            baseline_binding = {
                "baselinePath": str(base),
                "baselineRun": str(base),
                "baselineSha256": _sha256_file(base / "stdout.jsonl")
                if (base / "stdout.jsonl").is_file() else None,
                "baselinePreparedSha256": _sha256_file(base / "prepared.json")
                if (base / "prepared.json").is_file() else None,
                "decodedIndependently": True,
                "decodedRecordCount": len(decoded) if isinstance(decoded, (list, tuple)) else None,
                "baselineSession": {
                    k: session_doc.get(k) for k in
                    ("pid", "tid", "processCreation", "threadCreation", "image")
                },
                "baselineLevelId": prepared_doc.get("levelId"),
                "sessionMatches": None,   # 拿到本次 session 后回填
                "levelIdMatches": None,   # 拿到本次 levelId 后回填
                "normalizedSpecSha256": (spec_binding or {}).get("specSha256"),
                "hasBaselineSnapshot": (base / "baseline-snapshot.bin").is_file(),
                "note": (
                    "基线用共享 build_readonly_profile 的独立解码路径验证（不是只看文件存在），"
                    "并绑定会话与关卡。"
                ),
                "launchableFromBaseline": False,
            }
            snapshot_src = base / "baseline-snapshot.bin"
            if snapshot_src.is_file():
                baseline_inputs = {"snapshotBytes": snapshot_src.read_bytes()}

        session: dict | None = None
        session_note: dict = {}
        if not args.compile_placeholder:
            session, deadline_ms, session_note = resolve_session(
                session_path=args.session, discover=bool(args.discover_session),
                deadline_seconds=int(args.deadline_seconds))
        elif args.synthetic_session_for_compile_only:
            # **合成会话，只为了能编出共享探针**：共享 hook_receipt_probe.cpp:15 有
            # ``static_assert(HR_TARGET_PID != 0 && HR_TARGET_TID != 0, "Global hooks are forbidden")``
            # —— 那是**正确**的 fail-closed：没有真实目标就不该建全局钩子。
            # 哨兵值刻意醒目（0x5EED…），回执标 syntheticSession:true，**强制不可派发**。
            session = {
                "schemaVersion": 1,
                "pid": 0x5EED0001, "tid": 0x5EED0002,
                "window": 0x5EED0003,
                "processCreation": 0x5EED0004, "threadCreation": 0x5EED0005,
                "image": str(DEFAULT_IMAGE),
                "source": "SYNTHETIC-SESSION-FOR-COMPILE-ONLY-NOT-A-REAL-TARGET",
                "callbackObserved": False,
            }
            deadline_ms = gettickcount64() + int(args.deadline_seconds) * 1000
            session_note = {
                "sessionSource": "synthetic-session-for-compile-only",
                "sessionVerified": False,
                "syntheticSession": True,
                "deadlineClock": "GetTickCount64",
                "warnings": [
                    "合成会话：仅为让共享探针的 fail-closed static_assert 通过，"
                    "从而验证 action 21 补丁**可编译**。**不是真实目标**，产物不可派发。"
                ],
            }
        else:
            deadline_ms = gettickcount64() + int(args.deadline_seconds) * 1000
            session_note = {
                "sessionSource": "compile-placeholder",
                "sessionVerified": False,
                "deadlineClock": "GetTickCount64",
                "warnings": ["--compile-placeholder：身份未核实，产物**不可派发**"],
            }

        run, root_note = _new_run_directory(args.root)
        # **可执行配置必须来自 --spec**：目标实体 id / kind / 两个 class 都是
        # 显式声明的实测值，**不从 kind 推导**（协调者硬规则）。
        # 没有 spec 时给一组明确的哨兵，并让 launchable 前置 validatedSpec=false。
        spec_macros = {
            "entityId": 0,
            "kind": 0,
            "wrapperClass": 0,
            "configClass": 0,
        }
        if spec_binding is not None:
            first = (spec_binding.get("kinds") or [{}])[0]
            def _as_int(value, default=0):
                if value is None:
                    return default
                if isinstance(value, int):
                    return value
                text = str(value).strip()
                try:
                    return int(text, 16) if text.lower().startswith("0x") else int(text)
                except ValueError:
                    return default
            host_id = 0
            raw_host = json.loads(Path(args.spec).read_text(encoding="utf-8-sig"))
            for key in ("entityId", "hostEntityId", "targetEntityId"):
                if raw_host.get(key) is not None:
                    host_id = _as_int(raw_host.get(key))
                    break
            spec_macros = {
                "entityId": host_id,
                "kind": _as_int(first.get("kind")),
                "wrapperClass": _as_int(first.get("wrapperClass")),
                "configClass": _as_int(first.get("configClass")),
            }
            if not spec_macros["entityId"]:
                raise MounterError(
                    "SPEC_ENTITY_ID_MISSING",
                    f"{args.spec} 缺 entityId/hostEntityId/targetEntityId；"
                    "action 21 的载荷必须指名**哪一个实体**，不得从 kind 推",
                )
        # 契约要求的两个输入文件：baseline-snapshot.bin 与 normalized-spec.json。
        if baseline_inputs:
            (run / "baseline-snapshot.bin").write_bytes(baseline_inputs["snapshotBytes"])
        else:
            # 没有真实 baseline 时**不伪造**：写一个零字节占位并在回执里标明。
            (run / "baseline-snapshot.bin").write_bytes(b"")
        if normalized_spec is not None:
            (run / "normalized-spec.json").write_text(
                json.dumps(normalized_spec, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
        else:
            (run / "normalized-spec.json").write_text(
                json.dumps({"schema": 1, "kind": FIXED_KIND, "actionCode": FIXED_ACTION_CODE,
                            "receiptVersion": FIXED_RECEIPT_VERSION, "scope": FIXED_SCOPE,
                            "kinds": [], "note": "未给 --spec；这是空配置，不可派发"},
                           ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
        # 基线绑定：会话/关卡必须与本次一致才有意义（没有现读会话时如实为 None）。
        if baseline_binding is not None:
            baseline_binding["sessionMatches"] = (
                None if session is None else
                all(baseline_binding["baselineSession"].get(k) == session.get(k)
                    for k in ("pid", "tid", "processCreation", "threadCreation"))
            )
        shared_before = _shared_source_hashes()
        source_hashes = _isolated_sources(run, anchors=anchors, kinds=kinds)
        edits = _apply_source_edits(run)
        generated = write_native_sources(run, anchors=anchors, kinds=kinds)
        config = _target_config(run, kinds=kinds, anchors=anchors, session=session,
                                deadline_ms=deadline_ms, launchable=session is not None,
                                spec_macros=spec_macros)
        shared_after = _shared_source_hashes()
        shared_unchanged = {k: (shared_before.get(k) == shared_after.get(k))
                            for k in sorted(set(shared_before) | set(shared_after))}

        pinned = {str(run / "target_config.h"): _sha256_file(run / "target_config.h")}
        wrapper_text = _wrapper_script(run, pinned, config["deadlineUtc"])
        (run / FIXED_WRAPPER_NAME).write_text(wrapper_text, encoding="utf-8")

        # **派发独立闸门，默认关**：编译可以完成，但能不能派发是**另一件事**。
        dispatch_gate = {
            "gateOpen": False,
            "defaultState": "closed",
            "reason": (
                "派发是一道**独立的显式闸门**，默认 fail-closed；开发期不允许打开。"
                "打开它需要 leader 的统一阶段显式授权 + reviewer 复核 + 现读会话。"
            ),
            "requirements": [
                "verified live session (pid/tid/window/creation from a fresh read)",
                "reviewer sign-off on this run's build-result.json",
                "leader's exclusive native window",
            ],
            "openedBy": None,
        }
        claim = {
            "schema": 1,
            "kind": FIXED_KIND.replace("-build-", "-prepared-"),
            "tool": TOOL,
            "run": str(run),
            "sourceRun": str(run),
            "kindTag": FIXED_KIND,
            "actionCode": FIXED_ACTION_CODE,
            "receiptVersion": FIXED_RECEIPT_VERSION,
            "scope": FIXED_SCOPE,
            "levelId": None,
            # **诚实标注**：编译完成 = true；注入/启动/派发一律 false。
            "compiled": False,
            "injected": False,
            "launched": False,
            "dispatched": False,
            "dispatchGate": dispatch_gate,
            "reviewed": False,
            "allowWrites": False,
            "createdUtc": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "nonce": config["nonce"],
            "deadlineMs": config["deadlineMs"],
            "deadlineUtc": config["deadlineUtc"],
            "deadlineClock": config["deadlineClock"],
            # 消息 ID：真注册值 + 名字（可复算）+ 来源。**同一值**进 header 与本文件。
            "messageId": config["messageId"],
            "messageName": config["messageName"],
            "messageIdSource": config["messageIdSource"],
            "messageIdRegistered": config["messageIdRegistered"],
            "messageIdRange": config["messageIdRange"],
            "envelopeName": "envelope.json",
            # envelope 的 hash 不能写进 prepared.json 自己（它是在 prepared.json 之后
            # 才写出来的，且它自己引用 prepared 的 hash）—— 只记名字，hash 进回执与 build-result。
            "envelopeName": "envelope.json",
            "kindCount": len(kinds),
            "kinds": list(kinds),
            "kindEvidence": [kind_evidence(k) for k in kinds],
            "evidenceGateBypassed": bool(args.allow_unverified_kinds),
            "specBinding": spec_binding,
            "baselineBinding": baseline_binding,
            "wrapperName": FIXED_WRAPPER_NAME,
            "sourceHashes": source_hashes,
            # 证据**持久化进 run 目录**（不只出现在回执 stdout 里）：审计者事后
            # 也能在 prepared.json 里核「改动只发生在副本内」与「共享件前后未变」。
            "isolatedCopyEdits": edits,
            "sharedSourceHashesBefore": shared_before,
            "sharedSourceHashesAfter": shared_after,
            "sharedSourcesUnchanged": shared_unchanged,
            "sharedSourcesUntouched": all(shared_unchanged.values()),
            "rootPolicy": root_note,
            "session": config["session"],
            "sessionResolution": session_note,
            "identityPlaceholder": config["identityPlaceholder"],
            "nativeCalled": False,
            "writesGameBytes": False,
        }
        prepared_path = run / "prepared.json"
        prepared_path.write_text(json.dumps(claim, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
        borrowed = {
            rel: (_sha256_file(REPO_ROOT / rel) if (REPO_ROOT / rel).is_file() else None)
            for rel in SHARED_MUST_NOT_CHANGE
        }
        inventory = sorted(
            p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()
        )
        kind = str(kinds[0]) if kinds else "0"
        # **三处相等**：header / prepared.json / build-result.json 都带同一个 messageId。
        # 值来自 prepare 里**真的** RegisterWindowMessageW（在 target_config 生成时取的），
        # **没有任何下游替它编一个数**。
        message_id = int(config["messageId"])
        envelope = {
            "schemaVersion": 1,
            "kind": "mondstadt-combat-envelope-v1",
            "workId": "combat-native-mounter",
            "run": str(run),
            "actionCode": FIXED_ACTION_CODE,
            "receiptVersion": FIXED_RECEIPT_VERSION,
            "scope": FIXED_SCOPE,
            "kindTag": FIXED_KIND,
            # 固定 envelope 也携带该值（root 的 transport 读这里，不自己造）
            "messageId": message_id,
            "messageName": config["messageName"],
            "messageIdSource": config["messageIdSource"],
            "nonce": config["nonce"],
            "deadlineMs": config["deadlineMs"],
            "wrapperName": FIXED_WRAPPER_NAME,
            "preparedSha256": _sha256_file(prepared_path),
            "injected": False,
            "launched": False,
            "dispatched": False,
            "note": "固定 envelope：root transport 从这里取值；**transport 不注册、不造值**。",
        }
        envelope_path = run / "envelope.json"
        envelope_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
        _emit(receipt("prepare", {
            "run": str(run),
            "runRelativeToRepo": run.relative_to(REPO_ROOT).as_posix(),
            "preparedCard": str(prepared_path),
            "preparedSha256": _sha256_file(prepared_path),
            "inventory": inventory,
            "inventoryCount": len(inventory),
            "sourceCopyHashes": source_hashes,
            "generated": generated,
            "targetConfig": config,
            "wrapperPath": str(run / FIXED_WRAPPER_NAME),
            "wrapperSha256": _sha256_file(run / FIXED_WRAPPER_NAME),
            "anchors": resolved["anchors"],
            "anchorChecks": resolved["checks"],
            "kinds": list(kinds),
            "kindCount": len(kinds),
            "reservedNumbers": {"action": FIXED_ACTION_CODE,
                                "receiptProtocol": FIXED_RECEIPT_VERSION},
            # ---- Q1 硬条件：只改副本的差集证据 + 共享件 sha256 证据 ----
            "isolatedCopyEdits": edits,
            "sharedSourceHashesBefore": shared_before,
            "sharedSourceHashesAfter": shared_after,
            "sharedSourcesUnchanged": shared_unchanged,
            "sharedSourcesUntouched": all(shared_unchanged.values()),
            "borrowedSourcesUnchanged": borrowed,
            "rootPolicy": root_note,
            "sessionResolution": session_note,
            "specBinding": spec_binding,
            "baselineBinding": baseline_binding,
            "dispatchGate": dispatch_gate,
            "compiled": False,
            "injected": False,
            "launched": False,
            "dispatched": False,
            "nativeCalled": False,
        }, True))
        return 0
    except MounterError as exc:
        _emit(receipt("prepare", exc.as_dict(), False,
                      blocked="prepare 未完成 ⇒ **没有**可派发的候选目录"))
        return 1


def _vcvars() -> Path:
    import os
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / \
        "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise MounterError("MSVC_VSWHERE_MISSING", f"{vswhere} 不存在")
    import subprocess
    try:
        out = subprocess.check_output(
            [str(vswhere), "-latest", "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            text=True, timeout=60).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise MounterError("MSVC_DISCOVERY_FAILED", f"{type(exc).__name__}: {exc}") from None
    vcvars = Path(out) / "VC/Auxiliary/Build/vcvars64.bat"
    if not out or not vcvars.is_file():
        raise MounterError("MSVC_REQUIRED", f"vcvars64.bat 不存在：{vcvars}")
    return vcvars


#: 事件根：不需要入边（由引擎事件驱动）。
GRAPH_EVENT_ROOTS = frozenset({374, 375, 380, 620, 304, 373})
#: ~~已知不可写的口~~ —— **本条已作废（2026-10-17 修正）**。
#:
#: 旧写法把 725[3:1] 一概当成「type-27 所以不可写」。那是**过时判断**：
#: `AuthorWriteDict` 与 `tools/graph-dictionary-values` 已**严格核验** 708/710 的真实 type-27
#: 字典端口可写（storage **10003**、key ConfigID uint / value Int32、payload
#: `{"dict":[{"key":{"uint":…},"value":{"int":…}}]}`、`slot="auto"`）。
#: ⇒ 725 必须**按 catalog 实核其具体 generic 类型**，**不得以「它属于字典类型」一概禁止**。
#:
#: 下面是**实核结果**（`data/node-workbench/catalog.json` 的 725 声明）：
GRAPH_PORT_DECLARATIONS = {
    ("set_loot", 3, 1): {
        "nameZh": "战利品掉落字典",
        "serverParamType": 27,
        "storageKind": 10003,
        "source": "catalog.json nodes[definitionId=725].ports[key='3:1'].live",
        "verdict": "IN_SUPPORTED_DICT_FAMILY",
        "why": "serverParamType 27 + storage 10003 ⇒ 与**已严格核验可写**的 708/710 同为 10003 容器族；"
               "**不再一概禁止**。",
        "stillRequiredBeforeWrite": [
            "该口在 catalog 中必须**非连接**（未被上游接走）",
            "键/值叶类型必须落在 `auto` 已支持集合内（storage1+uint / storage2+int / storage6+uint(enum)）"
            "—— 725 的 f105 叶声明需按节点资源另行实核（**本轮未做**）",
            "须用**新建空白节点**写一次（writer 是**追加**，不是替换/清空）",
        ],
    },
}
#: 仍然**禁止**的口：只有那些**实核后不属于已支持族**的。本轮为空集。
GRAPH_UNWRITABLE_PORTS = frozenset()
#: 每个动作/查询节点的必需输入口（kind, index）。未列的节点不做必需口判定
#: —— 避免凭空规定端口。
GRAPH_REQUIRED_INPUTS = {
    724: ((1, 0), (3, 0)),
    725: ((1, 0),),   # **3:1 不列**：它是可选内容口且不可写
    727: ((1, 0),),
    726: ((1, 0), (3, 0)),
    1: ((1, 0),),
}


def graph_dangling_problems(doc: dict, *, inject_orphan_at: str | None = None) -> list[str]:
    """判定默认图里有没有悬空节点。**本函数自己实现，不吃产物自陈。**

    规则：
      1. 非事件根节点必须有**入边**；
      2. 每个「必需输入口」必须**有值或有入边**；
      3. 每条边的 from/to 必须在 nodes 里；
      4. 被 ``excludedNodes`` 排除的 definitionId 不得在场；
      5. 不得接/写**不可写口**（type-27）。
    """
    problems: list[str] = []
    for camp in doc.get("camps") or []:
        ref = camp.get("campRef", "?")
        if inject_orphan_at == ref:
            camp = json.loads(json.dumps(camp))
            camp["nodes"].append({"alias": "orphan_probe", "definitionId": 69,
                                  "x": 1500.0, "y": 0.0})
        aliases = {n["alias"]: n["definitionId"] for n in camp.get("nodes") or []}
        excluded = set(camp.get("excludedNodes") or [])
        written = {(v["node"], v.get("portIndex")) for v in camp.get("values") or []}
        incoming: dict[str, list[dict]] = {}
        for e in camp.get("edges") or []:
            if e["from"] not in aliases:
                problems.append(f"{ref}: edge.from={e['from']} 不在 nodes 里")
            if e["to"] not in aliases:
                problems.append(f"{ref}: edge.to={e['to']} 不在 nodes 里")
            incoming.setdefault(e["to"], []).append(e)
        for n in camp.get("nodes") or []:
            if n["definitionId"] in excluded:
                problems.append(f"{ref}: 被排除的 definitionId={n['definitionId']} 仍在 nodes 里")
        for alias, did in aliases.items():
            if did not in GRAPH_EVENT_ROOTS and alias not in incoming:
                problems.append(f"{ref}: 节点 {alias}(id={did}) 无入边 ⇒ 悬空")
            for (kind, idx) in GRAPH_REQUIRED_INPUTS.get(did, ()):
                has_value = (alias, idx) in written
                has_edge = any(e["toKind"] == kind and e["toIndex"] == idx
                               for e in incoming.get(alias, []))
                if not (has_value or has_edge):
                    problems.append(
                        f"{ref}: 节点 {alias}(id={did}) 的必需输入口 [{kind}:{idx}]"
                        f" 既无值又无入边 ⇒ 悬空")
        # **数据驱动**：只拒（a）显式列入 GRAPH_UNWRITABLE_PORTS 的口，
        # （b）已实核且 verdict 不属于已支持族的口。**不再按「属于 type-27」一概禁止。**
        for (alias, kind, idx) in GRAPH_UNWRITABLE_PORTS:
            if any(e["to"] == alias and e["toKind"] == kind and e["toIndex"] == idx
                   for e in camp.get("edges") or []):
                problems.append(f"{ref}: 有边接了具名不可写口 {alias}[{kind}:{idx}]")
            if (alias, idx) in written:
                problems.append(f"{ref}: 有值写了具名不可写口 {alias}[{idx}]")
        for (alias, kind, idx), decl in GRAPH_PORT_DECLARATIONS.items():
            if str(decl.get("verdict") or "").startswith("IN_SUPPORTED"):
                continue
            if any(e["to"] == alias and e["toKind"] == kind and e["toIndex"] == idx
                   for e in camp.get("edges") or []):
                problems.append(
                    f"{ref}: 有边接了**不在已支持族**的口 {alias}[{kind}:{idx}]"
                    f"（serverParamType={decl.get('serverParamType')} "
                    f"storage={decl.get('storageKind')}）")
    return problems


def cmd_graph_check(args) -> int:
    """``graph-check``：默认图无悬空节点 + 两条控制。"""
    plan = Path(args.plan)
    if not plan.is_file():
        raise MounterError("GRAPH_PLAN_MISSING", f"--plan {plan} 不存在")
    doc = read_json_safe(plan)
    if not isinstance(doc, dict) or not doc.get("camps"):
        raise MounterError("GRAPH_PLAN_SHAPE_INVALID", f"{plan} 不是默认图文档（缺 camps[]）")
    problems = graph_dangling_problems(doc)
    payload: dict = {
        "plan": str(plan),
        "planSha256": _sha256_file(plan),
        "noDangling": not problems,
        "problems": problems,
        "perCamp": [
            {"campRef": c.get("campRef"), "nodes": len(c.get("nodes") or []),
             "edges": len(c.get("edges") or []), "values": len(c.get("values") or []),
             "excludedNodes": c.get("excludedNodes") or []}
            for c in doc["camps"]],
    }
    if args.self_test:
        # 控制 1（正面）：故意插一个孤点，判定器**必须**报出来。
        pos = graph_dangling_problems(doc, inject_orphan_at="camp-a")
        orphan_caught = any("orphan_probe" in x for x in pos)
        # 控制 2（反面，**已换**）：旧的「接 725[3:1] 必须报 type-27」控制**已作废** ——
        # 因为 blanket type-27 禁令本身已被移除（708/710 已严格核验可写、725 实核为 storage 10003）。
        # 现在仍然有牙齿的控制是：**一个不在已支持族里的口声明必须被拒**。
        fake = ("set_loot", 3, 1)
        saved = dict(GRAPH_PORT_DECLARATIONS)
        try:
            GRAPH_PORT_DECLARATIONS[fake] = {
                "nameZh": "注入的不可写口探针",
                "serverParamType": 99,
                "storageKind": 4242,
                "verdict": "NOT_IN_SUPPORTED_FAMILY",
            }
            # 同时注入一条**接上该口**的边 —— 否则判定器看不到它（探针必须在场）。
            bad = json.loads(json.dumps(doc))
            bad["camps"][0].setdefault("edges", []).append(
                {"from": "trigger_loot", "to": "set_loot", "fromKind": 2, "fromIndex": 0,
                 "toKind": 3, "toIndex": 1})
            neg = graph_dangling_problems(bad)
            unsupported_caught = any("不在已支持族" in x for x in neg)
        finally:
            GRAPH_PORT_DECLARATIONS.clear()
            GRAPH_PORT_DECLARATIONS.update(saved)
        payload["controls"] = {
            "orphanInjectedCaught": orphan_caught,
            "orphanProblems": pos,
            "unsupportedPortCaught": unsupported_caught,
            "unsupportedPortProblems": neg,
            "obsoleteControlRetired": {
                "name": "type27EdgeCaught",
                "why": "blanket type-27 禁令已移除（708/710 已严格核验可写；725 实核 storage 10003）"
                       "⇒ 该控制不再有意义，**已换**为 unsupportedPortCaught",
            },
            "controlsAreReal": bool(orphan_caught and unsupported_caught),
        }
    _emit(receipt("graph-check", payload, payload["noDangling"]
                  and (not args.self_test or payload.get("controls", {}).get(
                      "controlsAreReal", False))))
    return 0 if payload["noDangling"] else 1


def _config_write_gate(kind_row: dict) -> tuple[bool, list[str]]:
    """**字段写入闸门**（在代码里执行，不是写文档）。

    三条同时满足才允许写字段：
      ① 配置类**专属**（不是被多个 kind 共用的通用记录）；
      ② 偏移来自 `field --ordinal` 的**类内声明序**域；
      ③ **固定 PE/SHA + 实际 native 方法访问/赋值/导出映射**给出该字段的语义依据。

    **2026-10-17 修正**：第 ③ 条**不再用字段名正则**。旧写法 `re.fullmatch(r"[A-Z]{8,12}")`
    **两个方向都错**：
      * **会误拒**——已由**方法代码确认**的混淆字段（它们是真实业务字段，只是名字被混淆）；
      * **会误收**——任意「看起来可读」的串（例：`EnmityValue` 只是**字符串池里的字面量**，
        不代表任何原生 setter/getter 读过它）。
    ⇒ 真实依据是**原生方法证据**，不是字面名。

    **并且**：本闸门**不是部署前置**。模板已带战斗所需组件时，这条研究可以保持未完成，
    不阻塞任何部署（见 mount-plan 的 verdict 语义）。
    返回 (allow, reasons)。
    """
    reasons: list[str] = []
    cf = kind_row.get("configurableFields") or {}
    classes = cf.get("classes") or []
    if not classes:
        reasons.append("① 未解到任何配置类（无 classes[]）")
    for c in classes:
        if "共用" in str(c.get("caveat") or ""):
            reasons.append(f"① 类 {c.get('obfuscatedName')}({c.get('ownerIndex')}) 是**共享记录**")
    if not cf.get("offsets") and not any(c.get("offsets") for c in classes):
        reasons.append("② 没有可用偏移")
    # ③ **原生方法证据**（不是字面名）
    method_evidence = []
    for c in classes:
        method_evidence.extend(c.get("fieldMethodEvidence") or [])
    method_evidence.extend(cf.get("fieldMethodEvidence") or [])
    has_real_evidence = False
    for ev in method_evidence:
        if (ev.get("imageSha256") or ev.get("peSha256")) and (
                ev.get("access") or ev.get("assign") or ev.get("export")):
            has_real_evidence = True
    if not has_real_evidence:
        reasons.append(
            "③ 缺**原生方法证据**（需要：固定 PE/SHA + 对该字段的实际 native 访问/赋值/导出映射）"
            "；字段名是否为混淆串**与语义无关**，故不再作为判据（旧的 [A-Z]{8,12} 正则已移除）")
    return (not reasons), reasons


def cmd_mount_plan(args) -> int:
    """``mount-plan``：读 kind 解析与生产候选，输出**挂载与字段配置计划**并执行写入闸门。

    它是**真闸门**：不过时给出具名原因，而不是把「不写」包装成成功。
    """
    kfr_path = REPO_ROOT / (args.kind_fields
                            or "data/mondstadt/combat/kind-field-resolutions.json")
    pc_path = REPO_ROOT / (args.candidate
                           or "data/mondstadt/combat/production-candidate.json")
    for p in (kfr_path, pc_path):
        if not p.is_file():
            raise MounterError("MOUNT_PLAN_INPUT_MISSING", f"{p} 不存在")
    kfr = read_json_safe(kfr_path)
    pc = read_json_safe(pc_path)
    if not isinstance(kfr, dict) or not isinstance(pc, dict):
        raise MounterError("MOUNT_PLAN_INPUT_INVALID", "输入不是 JSON 对象")
    mount = pc.get("mountAndConfigure") or {}
    rows = mount.get("perKind") or []
    if not rows:
        raise MounterError("MOUNT_PLAN_EMPTY",
                           "production-candidate 里没有 mountAndConfigure.perKind")

    per_kind = []
    writable = []
    for row in rows:
        allow, reasons = _config_write_gate(row)
        if allow:
            writable.append(row.get("kind"))
        per_kind.append({
            "kind": row.get("kind"),
            "name": row.get("name"),
            "attachRequired": bool(row.get("attachRequired")),
            "templateCarries": bool(row.get("templateCarries")),
            "fieldWriteAllowed": allow,
            "blockedBy": reasons,
            "resolutionStatus": next((k.get("status") for k in (kfr.get("perKind") or [])
                                      if k.get("kind") == row.get("kind")), None),
        })
    payload = {
        "kindFieldResolutions": str(kfr_path.relative_to(REPO_ROOT).as_posix()),
        "candidate": str(pc_path.relative_to(REPO_ROOT).as_posix()),
        "attachRequiredForCombat": bool(mount.get("attachRequiredForCombat")),
        "perKind": per_kind,
        "writableKinds": writable,
        "fieldWritesPlanned": len(writable),
        "policy": (mount.get("configurationPolicy") or {}).get("rule"),
        "gateBasis": "③ 的原生方法证据（固定 PE/SHA + native 访问/赋值/导出映射）；"
                     "**字段名正则已移除**（两个方向都会错）",
        "isDeploymentPrerequisite": False,
        "prerequisiteNote": "**本闸门不是部署前置**：模板已带战斗所需组件（26/4/9/12+18/11+20/19）"
                            "⇒ 该研究未完成**不阻塞** spawn / 图 / HP·死亡 / loot 任一环节。",
        "graphPortPolicy": {
            "blanketType27BanRemoved": True,
            "why": "`AuthorWriteDict` + tools/graph-dictionary-values 已严格核验 708/710 的真实 type-27 "
                   "字典端口可写（storage 10003）⇒ 「所有 type-27 绝对不可写」已过时。",
            "declared": {f"{a}[{k}:{i}]": v for (a, k, i), v in GRAPH_PORT_DECLARATIONS.items()},
            "stillForbidden": sorted(f"{a}[{k}:{i}]" for (a, k, i) in GRAPH_UNWRITABLE_PORTS),
        },
        "verdict": ("NO_FIELD_WRITES_ALLOWED" if not writable
                    else f"FIELD_WRITES_ALLOWED_FOR:{writable}"),
        "honestNote": ("**0 个 kind 通过写入闸门** ⇒ 不做任何字段写入。战斗实现是**模板原生 + 图**，"
                       "组件写入不是它的前置 ⇒ 这不是「用 fail-closed 当战斗实现」。"
                       if not writable else "有 kind 通过闸门；仍需真会话与基线才能执行。"),
    }
    _emit(receipt("mount-plan", payload, True))
    return 0


def cmd_override_card(args) -> int:
    """``override-card``：把**必要覆盖**落成可调用卡（argv + dispatch + readback）。

    三件事必须同时在卡里，否则它不是「可调用」的：
      * **argv**：逐条可复制执行的命令（不是散文步骤）；
      * **dispatch**：真的怎么派发（队列/提权 helper/build-plan 一次派发）+ 前置；
      * **readback**：读什么、怎么比、什么才算证据。
    """
    run = Path(args.run)
    if not run.is_dir():
        raise MounterError("RUN_DIRECTORY_MISSING", f"--run {run} 不是目录")
    prepared = read_json_safe(run / "prepared.json")
    if not isinstance(prepared, dict):
        raise MounterError("PREPARED_CARD_MISSING", f"{run}/prepared.json 不存在或不可解析")
    graph_doc = read_json_safe(REPO_ROOT / "data/mondstadt/combat/combat-graph-default.json")
    handover = read_json_safe(REPO_ROOT / "data/mondstadt/combat/leader-handover.json")
    if not isinstance(graph_doc, dict):
        raise MounterError("GRAPH_PLAN_MISSING",
                           "data/mondstadt/combat/combat-graph-default.json 不可解析")
    camps = graph_doc.get("camps") or []
    if args.camp:
        camps = [c for c in camps if c.get("campRef") == args.camp]
        if not camps:
            raise MounterError("CAMP_NOT_IN_PLAN",
                               f"--camp {args.camp} 不在默认图里（有 "
                               f"{[c.get('campRef') for c in graph_doc.get('camps') or []]}）")

    # **必要覆盖**：只有两项，且都不是组件挂载（组件挂载本题不需要）。
    overrides = [
        {
            "id": "OVR-CREATE-COORDS",
            "what": "按坐标创建（24 生物走单体 + 12 陈设走批量）",
            "whyNecessary": "模板定义「这是什么」，不定义「放在哪」；位置必须由我们给。",
            "classFactoryFieldsSetter": {
                "class": "scene entity",
                "factory": "tools/game-executor/scene_cli.py:258-266（create / creature-create 一次性收 position/rotation/scale）；批量在同文件 :170-192",
                "fields": "position / rotation / scale",
                "setter": "**创建参数**（首选）。**注意：旧的「对已有实体没有 transform setter」已作废** —— "
                          "已有**独立 entity-transform 能力**，建后也能搬；建时给全只是少一次写入、少一个失败面。",
            },
            "argv": [
                "python -B tools/game-executor/scene_cli.py creature-create --place-builtin 1 "
                "--template-id <templateId> --position <x,y,z> --rotation <rx,ry,rz> --scale 1,1,1",
                "python -B tools/game-executor/scene_cli.py create-batch "
                "--placements plans/<camp>.placements.json",
            ],
            "perItemRef": "data/mondstadt/combat/camp-instances.json（24 生物 + 12 陈设）；"
                          "紧凑形式见 leader-handover.json createCandidates",
            "dispatch": {
                "channel": "scene_cli（原生通道）",
                "when": "**必须在 terrain 读回之后** —— y 未对齐前不要建（会悬空或埋入）",
                "oneAtATime": "生物一律**单体**：批量放 3xxxxxxx 生物从未被测过",
            },
            "readback": {
                "what": "实体表差分",
                "how": "创建前读实体表 ⇒ 创建后读实体表 ⇒ 新增条数必须等于创建条数",
                "verifyBy": "实体表 owner/config/context/id/configId",
                "forbidden": ["**不要**用 placedCount 判放置成功（单体路径该计数恒为 0）"],
            },
            "blockedBy": [],
            "coordinatesIn": "data/mondstadt/combat/production-candidate.json → creationCoordinates"
                             "（36 个真实创建坐标，y 已由**精确格高度**填上）",
            "yResolved": "旧的 Y-GROUND-GAP **已作废**：栅格 cells 5402 → 11017，36/36 "
                         "hasSample=true、nearestFallback=false、nearestCellDistance=0.0。"
                         "**但 provisional=true（ASSUMED-DATUM）⇒ 只可相对比较，不得称实测。**",
        },
        {
            "id": "OVR-GRAPH-WIRING",
            "what": "关卡侧交战接线（默认图**无悬空节点**）",
            "whyNecessary": "模板带来仇恨/追击/攻击的**能力**；「哪一个实体、什么条件下入战」是本关的编排。",
            "classFactoryFieldsSetter": {
                "class": "节点图（graphKind 20000，唯一有 playtest 证据的服务端 kind）",
                "factory": "tools/authoring/author.py build-plan（整张图一次派发）",
                "fields": "nodes / edges / values",
                "setter": "图节点值 + 连线；**落图必须靠一次 native save**",
            },
            "argv": [
                "python -B tools/authoring/author.py build-plan --plan <combat-graph-default 的某营地>",
                "python -B tools/game-executor/scene_cli.py save",
                "python -B tools/beyond-save/field_diff.py <before.gil> <after.gil>",
            ],
            "perCamp": [
                {"campRef": c["campRef"], "graphNativeName": c["graphNativeName"],
                 "nodes": len(c.get("nodes") or []), "edges": len(c.get("edges") or []),
                 "values": len(c.get("values") or []), "excludedNodes": c.get("excludedNodes") or []}
                for c in camps],
            "dispatch": {
                "channel": "提权 helper 队列（tools/editor-bridge/start-elevated.ps1）→ build-plan",
                "whyOneDispatch": "整图派发是**首选**（少一次派发往返）。**注意：旧的「scope 租约 5 分钟 ⇒ 必须并成一次」已作废** —— root 已提供生产 `scope_renew`，**分批派发同样合法**，不再据此约束交付。",
                "then": "build+bind 之后**必须**一次 native save（编辑器保存按钮不落图）",
                "precondition": "派发前**逐字节备份 .gil**",
            },
            "readback": {
                "what": ".gil 字段差分 + 独立读回节点图",
                "how": "field_diff.py <before> <after>",
                "forbidden": ["**不看文件大小**：field 46 的更新式含 prepend-and-evict-tail，可等长改字节",
                              "**不得把 print-string 当交战状态**"],
            },
        },
    ]
    card = {
        "schemaVersion": 1,
        "kind": "mondstadt-combat-override-card-v1",
        "contractVersion": FIXED_RECEIPT_VERSION,
        "actionCode": FIXED_ACTION_CODE,
        "workId": "combat-native-mounter",
        "planRevision": 7,
        "run": str(run),
        "camp": args.camp,
        # **可调用**：与 run 的 messageId 同源（三处相等的那一个）。
        "messageId": prepared.get("messageId"),
        "messageName": prepared.get("messageName"),
        "messageIdSource": prepared.get("messageIdSource"),
        "nonce": prepared.get("nonce"),
        "componentAttachRequired": False,
        "componentAttachWhy": "战斗能力随模板到达（26 Enmity / 4 Mover / 9 FollowMove / "
                              "12 HitDetection + 18 Combat / 11 BulletMove + 20 BulletPattern / "
                              "19 Hitbox）⇒ **不重复挂未知组件**。依据 inherited-behaviour.json。",
        "requiredOverrides": overrides,
        "excludedOptional": graph_doc.get("excludedFromDefault") or [],
        "graphDanglingFree": not graph_dangling_problems(graph_doc),
        "blockedBy": [],
        "retracted": [
            {"claim": "Y-GROUND-GAP / FAIL_CLOSED_MEASURED_GAP / GROUND_RASTER_DOES_NOT_COVER_COMBAT_CAMPS",
             "why": "**已作废**：栅格 cells 5402 → **11017**，36/36 `hasSample=true`、`nearestFallback=false`、"
                    "`nearestCellDistance=0.0` ⇒ 精确格命中、无兜底。不需扩栅格、不需改选址。",
             "newValue": "y 已由精确格高度填入 data/mondstadt/combat/production-candidate.json"},
            {"claim": "scope 租约 5 分钟做不了几十个 op，必须并成一次 build-plan",
             "why": "**不成立**：root 已提供生产 `scope_renew` ⇒ 分批或整图派发都合法。"},
            {"claim": "只有 transform、没有 setter（TRANSFORM_NATIVE_SETTER_UNKNOWN）",
             "why": "**不成立**：已有**独立 entity-transform 能力**，建后也能搬。建时给全坐标是首选而非约束。"},
        ],
        "neverClaimed": "**不得把 print-string 当战斗**：mark_* 只是可捕获标记，不是交战/受击/死亡证据。"
                        "战斗证据是**实体表 + 原生 HP**（见 observationEntryPoints）。",
        "groundProvisional": {
            "provisional": True,
            "datumStatus": "ASSUMED-DATUM",
            "originReplaceRequired": True,
            "warn": "全部 36 个 y 来自 `provisional:true` 的地面数据 ⇒ **只可相对比较，不得称实测**；"
                    "统一阶段须以原生只读读回替换 origin 并复核法则后重算。",
        },
        "codeTable": OVERRIDE_CARD_CODES,
        "handover": {
            "file": "data/mondstadt/combat/leader-handover.json",
            "monsters": ((((handover or {}).get("createCandidates") or {}).get("monsters")
                          or {}).get("count")),
            "props": ((((handover or {}).get("createCandidates") or {}).get("props")
                       or {}).get("count")),
            "creationAuthority": (handover or {}).get("creationAuthority"),
        },
        "productionCandidate": {
            "file": "data/mondstadt/combat/production-candidate.json",
            "coordinates": "creationCoordinates（36 条，y 已填）",
            "completeGraphs": "completeGraphs.camp-a/b/c（各 10 节点 / 7 边 / 6 值）",
            "observationEntryPoints": "observationEntryPoints（8 条）",
        },
        "honestBoundary": {
            "reallyRan": ["无。本卡没有执行任何一条 argv：没有创建实体、没有派发、没有 save、没有读回。"],
            "argvArePaths": "卡里的 argv 是**既有实现里的真实命令形状**（逐个来自 scene_cli.py / author.py / field_diff.py），"
                            "但**没有一条在本营地执行过**。",
        },
    }
    out = Path(args.out) if args.out else (run / "override-card.json")
    out.write_text(json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _emit(receipt("override-card", {
        "cardPath": str(out),
        "cardSha256": _sha256_file(out),
        "camp": args.camp,
        "componentAttachRequired": False,
        "requiredOverrides": [o["id"] for o in overrides],
        "graphDanglingFree": card["graphDanglingFree"],
        "blockedBy": [b["id"] for b in card["blockedBy"]],
        "messageId": card["messageId"],
    }, True))
    return 0


#: 覆盖卡里带的具名码表（真实 API 错误都带 code，便于继续修复）。
OVERRIDE_CARD_CODES = [
    {"code": "ENTITY_TRANSFORM_UNAVAILABLE", "when": "独立 entity-transform 能力不可用",
     "fix": "**首选在创建那一刻给全坐标**（production-candidate.json 的 36 个坐标）；"
            "注意：旧的「对已有实体没有 setter / TRANSFORM_NATIVE_SETTER_UNKNOWN」**已作废**"},
    {"code": "COMPONENT_MODEL_READER_UNBOUND", "when": "组件读半未绑定", "fix": "走节点面 + 实体表差分"},
    {"code": "INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED", "when": "指令图删除缺编辑对象 id",
     "fix": "本链不删指令图"},
    {"code": "ABI_ANCHOR_BUILD_DRIFT", "when": "锚点 head32 与档案不等（游戏更新）", "fix": "重推 RVA"},
    {"code": "MESSAGE_ID_MISMATCH", "when": "header/prepared/envelope 三处 messageId 不等",
     "fix": "重跑 prepare"},
    {"code": "UNVERIFIED_KINDS_FORBIDDEN_ON_PRODUCTION_PATH",
     "when": "非 compile-only 用了 --allow-unverified-kinds", "fix": "加 --compile-placeholder"},
    {"code": "GRAPH_PLAN_MISSING", "when": "默认图文件不可解析", "fix": "查 data/mondstadt/combat/combat-graph-default.json"},
    {"code": "RUN_DIRECTORY_MISSING", "when": "--run 不是目录", "fix": "先跑 prepare"},
    {"code": "PREPARED_CARD_MISSING", "when": "run 里没有 prepared.json", "fix": "先跑 prepare"},
    {"code": "CAMP_NOT_IN_PLAN", "when": "--camp 不在默认图里", "fix": "用 camp-a/camp-b/camp-c"},
]


def cmd_compile_check(args) -> int:
    """对候选做**编译 + 布局探针 + 守卫驱动**。只编译不派发，零游戏写入。"""
    import subprocess
    run = Path(args.run)
    try:
        if not run.is_dir():
            raise MounterError("RUN_DIRECTORY_MISSING", f"{run} 不存在")
        run = _require_inside_runtime(run, allowed_roots=ALLOWED_WRITE_ROOTS)
        if not (run / "prepared.json").is_file():
            raise MounterError("NOT_A_PREPARED_RUN", f"{run}/prepared.json 不存在；先跑 prepare")
        if (run / "launch.claim").exists():
            raise MounterError(
                "RUN_ALREADY_DISPATCHED",
                f"{run} 已有 launch.claim ⇒ 已派发过，禁止再编译/重放",
            )
        generated = run / "component_mounter_native.cpp"
        driver = run / "mounter_driver.cpp"
        if not generated.is_file() or not driver.is_file():
            raise MounterError("GENERATED_SOURCES_MISSING", f"{generated} / {driver}")
        vcvars = _vcvars()

        # 布局探针的 TU：只 include 生成物 + 打印编译器给的数字。
        probe_text = _layout_probe_source()
        probe_path = run / "receipt_layout_probe.cpp"
        probe_path.write_text(probe_text, encoding="utf-8")

        common = (
            f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 '
            f'/FI"{run / "target_config.h"}" '
            # /I 指向 run 根：适配 TU 要 #include 生成物 component_mounter_native.cpp
            # （它落在 run 根，与候选源树分开）。
            f'/I"{run}" '
        )
        commands = [
            "@echo off",
            f'call "{vcvars}" >nul',
            "if errorlevel 1 exit /b 1",
            # 1) 生成物必须能作为独立 TU 编译
            common + f'/c "{generated}" /Fo:"{run / "component_mounter.obj"}"',
            "if errorlevel 1 exit /b 1",
            # 2) 布局探针（包含生成物 → 它测的就是生成物本身的 ABI）
            common + f'"{probe_path}" /Fo:"{run / "receipt_layout_probe.obj"}" '
                     f'/Fe:"{run / "receipt_layout_probe.exe"}"',
            "if errorlevel 1 exit /b 1",
            f'"{run / "receipt_layout_probe.exe"}" > "{run / "receipt-layout.json"}"',
            "if errorlevel 1 exit /b 1",
            # 3) 守卫驱动（进程内桩内存；真实调用一次 attach 并断言）
            common + f'"{driver}" /Fo:"{run / "mounter_driver.obj"}" '
                     f'/Fe:"{run / "mounter_driver.exe"}"',
            "if errorlevel 1 exit /b 1",
            f'"{run / "mounter_driver.exe"}" "{run}" > "{run / "driver.log"}"',
            "if errorlevel 1 exit /b 1",
        ]
        # 4) 固定 action 的**真实 native 产物**：hook_receipt.dll + hook_receipt_probe.exe。
        #    按 build_generalized.compile_run(layout_only=False) 的同形做法编出来 ——
        #    **编译 ≠ 派发**：产物只留在候选目录里，不注入、不加载、不启动、不碰游戏。
        native_src = run / "candidate-source/native"
        hook_dll = run / "hook_receipt.dll"
        probe_exe = run / "hook_receipt_probe.exe"
        if (native_src / "hook_receipt.cpp").is_file():
            commands += [
                common + f'/c "{native_src / "game_context_snapshot.cpp"}" '
                         f'/Fo:"{run / "game_context_snapshot.obj"}"',
                "if errorlevel 1 exit /b 1",
                # 适配 TU：定义 action 21 的执行入口（链接进 DLL）
                common + f'/c "{native_src / COMBAT_ADAPTER_IMPL}" '
                         f'/Fo:"{run / "combat_component_mount.obj"}"',
                "if errorlevel 1 exit /b 1",
                common + f'/LD "{native_src / "hook_receipt.cpp"}" '
                         f'/Fo:"{run / "hook.obj"}" /Fe:"{hook_dll}" '
                         f'/link User32.lib "{run / "game_context_snapshot.obj"}" '
                         f'"{run / "combat_component_mount.obj"}"',
                "if errorlevel 1 exit /b 1",
                # 固定探针 = **共享探针的候选副本**（已由 _source_edits 扩展 action 21）
                common + f'"{native_src / "hook_receipt_probe.cpp"}" '
                         f'/Fo:"{run / "probe.obj"}" /Fe:"{probe_exe}" '
                         f'/link User32.lib Advapi32.lib',
                "if errorlevel 1 exit /b 1",
            ]
        (run / "build.cmd").write_text("\n".join(commands) + "\n", encoding="utf-8")
        result = subprocess.run(["cmd.exe", "/d", "/c", str(run / "build.cmd")], cwd=str(run),
                                capture_output=True, text=True, timeout=600)
        (run / "build.log").write_text((result.stdout or "") + (result.stderr or ""),
                                       encoding="utf-8")
        if result.returncode != 0:
            raise MounterError(
                "BUILD_FAILED",
                f"build.cmd 退出码 {result.returncode}；日志 {run / 'build.log'} "
                f"末尾：{((result.stdout or '') + (result.stderr or ''))[-400:]}",
            )
        layout_path = run / "receipt-layout.json"
        if not layout_path.is_file():
            raise MounterError("LAYOUT_PROBE_MISSING", f"{layout_path} 未生成")
        layout = json.loads(layout_path.read_text(encoding="utf-8-sig"))
        layout_check = _check_layout(
            layout, expected_kind_count=int(json.loads(
                (run / "prepared.json").read_text(encoding="utf-8-sig"))["kindCount"]))
        driver_text = (run / "driver.log").read_text(encoding="utf-8", errors="replace")
        if "DRIVER_OK" not in driver_text or "DRIVER_FAILED" in driver_text:
            raise MounterError(
                "GUARD_DRIVER_FAILED",
                f"驱动没有报告 DRIVER_OK：{driver_text.strip().splitlines()[-3:]}",
            )
        assertions = [line for line in driver_text.splitlines() if line.startswith(("ok ", "FAIL"))]
        failed_assertions = [line for line in assertions if line.startswith("FAIL")]

        # prepare 时写的 wrapper 还没有产物 pin；编译完成后**重写一次**并配全 pin。
        pinned: dict[str, str] = {}
        for name in ("target_config.h", "build-result.json", "hook_receipt_probe.exe",
                     FIXED_WRAPPER_NAME, "receipt-layout.json", "driver.log"):
            path = run / name
            if path.is_file() and name != FIXED_WRAPPER_NAME:
                pinned[str(path)] = _sha256_file(path)
        prepared = json.loads((run / "prepared.json").read_text(encoding="utf-8-sig"))
        # **launchable 由真实构建结果决定**，不是硬编码：
        # 需要 ① 真实会话（非占位、四个身份值都非 0/1）
        #      ② 真的编出来的两个产物（DLL + probe）
        #      ③ 真实 baseline 绑定（--baseline 提供且独立解码过）
        #      ④ 规范化 spec 已校验（--spec 提供且 kinds 非空）
        session = prepared.get("session") or {}
        session_real = bool(
            not prepared.get("identityPlaceholder")
            and not (prepared.get("sessionResolution") or {}).get("syntheticSession")
            and all(isinstance(session.get(k), int) and session.get(k) not in (0, 1)
                    for k in ("pid", "tid", "processCreation", "threadCreation"))
        )
        baseline_binding = prepared.get("baselineBinding") or {}
        baseline_real = bool(baseline_binding and baseline_binding.get("decodedIndependently"))
        hashes_pre = prepared.get("hashes") or {}
        spec_doc = read_json_safe(run / "normalized-spec.json")
        spec_real = bool(spec_doc and (spec_doc.get("kinds") or [])
                         and (spec_doc.get("validation") or {}).get("allKindsHaveOwnerClassFields"))
        artifacts_real = (run / "hook_receipt.dll").is_file() and \
            (run / "hook_receipt_probe.exe").is_file()
        # 消息 ID 必须是**真注册值**：fixture 走不到生产（缺陷修复后的硬条件）。
        message_registered = prepared.get("messageIdSource") == "registered"
        launchable_gaps = [name for name, ok in (
            ("realSession", session_real),
            ("realBaseline", baseline_real),
            ("validatedSpec", spec_real),
            ("compiledArtifacts", artifacts_real),
            ("messageIdRegistered", message_registered),
        ) if not ok]

        # ---- **三处相等**：header == prepared.json == build-result.json（+ envelope）----
        # 由 compile-check 亲自从三份产物里读出来比，而不是相信任何一处自陈。
        def _header_message_id(path: Path) -> int:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#define HR_MESSAGE_ID "):
                    return int(line.split()[2].rstrip("ULL").rstrip("ull"))
            return -1

        header_mid = _header_message_id(run / "target_config.h")
        prepared_mid = int(prepared.get("messageId", -1))
        envelope_doc = read_json_safe(run / "envelope.json") or {}
        envelope_mid = int(envelope_doc.get("messageId", -1))
        message_id_equal = (header_mid == prepared_mid == envelope_mid != -1)
        if not message_id_equal:
            raise MounterError(
                "MESSAGE_ID_MISMATCH",
                f"三处必须相等：header={header_mid} prepared.json={prepared_mid} "
                f"envelope.json={envelope_mid}；不一致即 fail-closed",
            )
        if not (REGISTERED_MESSAGE_MIN <= header_mid <= REGISTERED_MESSAGE_MAX):
            raise MounterError(
                "MESSAGE_ID_OUT_OF_RANGE",
                f"messageId={header_mid:#x} 不在注册消息区间 "
                f"{REGISTERED_MESSAGE_MIN:#x}..{REGISTERED_MESSAGE_MAX:#x}",
            )
        launchable = not launchable_gaps
        if getattr(args, "require_launchable", False) and not launchable:
            raise MounterError(
                "LAUNCHABLE_PRECONDITIONS_UNMET",
                "要求可派发产物，但缺：" + ", ".join(launchable_gaps)
                + "。**不接受**用编译占位换取 launchable；请提供真实会话、"
                  "真实 baseline 与已校验 spec。",
            )
        wrapper_text = _wrapper_script(run, pinned, prepared["deadlineUtc"])
        (run / FIXED_WRAPPER_NAME).write_text(wrapper_text, encoding="utf-8")
        pinned[str(run / FIXED_WRAPPER_NAME)] = _sha256_file(run / FIXED_WRAPPER_NAME)

        hashes = {
            name: _sha256_file(run / name)
            for name in ("target_config.h", "baseline-snapshot.bin", "normalized-spec.json",
                         "receipt-layout.json", "build.cmd", "build.log",
                         "component_mounter.obj", "component_mounter_native.cpp",
                         "mounter_driver.cpp", "mounter_driver.exe",
                         "receipt_layout_probe.cpp", "receipt_layout_probe.exe",
                         "driver.log", "hook_receipt.dll", "hook_receipt_probe.exe",
                         "game_context_snapshot.obj", "combat_component_mount.obj",
                         "hook.obj", "combat-probe.json",
                         FIXED_WRAPPER_NAME, "prepared.json")
            if (run / name).is_file()
        }
        build_result = {
            "ok": True,
            "kind": FIXED_KIND,
            "run": str(run),
            # **诚实三分**：编译可以完成；注入/启动/派发一律 false。
            "compiled": True,
            "injected": False,
            "launched": False,
            "dispatched": False,
            # 契约：launchable 指「产物是真可启动的二进制」。它必须来自**真的编出来**
            # 的产物，且**不得**由 --compile-placeholder / 无会话路径获得。
            "launchable": launchable,
            "compileOnly": not launchable,
            "whyNotLaunchable": None if launchable else (
                "无已验证的真实会话（或用了 --compile-placeholder）⇒ 产物可以编译，"
                "但**不可派发**。launchable 必须来自真会话 + 真编出来的产物，"
                "不得用编译占位换取。"
            ),
            "actionCode": FIXED_ACTION_CODE,
            "receiptVersion": FIXED_RECEIPT_VERSION,
            "scope": FIXED_SCOPE,
            "wrapper": str(run / FIXED_WRAPPER_NAME),
            "wrapperName": FIXED_WRAPPER_NAME,
            "wrapperSha256": hashes[FIXED_WRAPPER_NAME],
            "nonce": prepared["nonce"],
            "deadline": prepared.get("deadlineMs"),
            "deadlineUtc": prepared["deadlineUtc"],
            # **三处相等之一**：与 header、prepared.json、envelope.json 同值。
            "messageId": prepared.get("messageId"),
            "messageName": prepared.get("messageName"),
            "messageIdSource": prepared.get("messageIdSource"),
            "messageIdRegistered": prepared.get("messageIdRegistered"),
            "messageIdRange": f"{REGISTERED_MESSAGE_MIN:#x}..{REGISTERED_MESSAGE_MAX:#x}",
            "envelopePath": str(run / "envelope.json"),
            "envelopeSha256": _sha256_file(run / "envelope.json")
            if (run / "envelope.json").is_file() else None,
            "messageIdChecks": {
                "header": header_mid,
                "preparedJson": prepared_mid,
                "envelopeJson": envelope_mid,
                "allEqual": message_id_equal,
                "inRegisteredRange": REGISTERED_MESSAGE_MIN <= header_mid <= REGISTERED_MESSAGE_MAX,
            },
            "session": prepared["session"],
            "sourceHashes": prepared["sourceHashes"],
            "hashes": hashes,
            "dispatchGate": prepared.get("dispatchGate"),
            "baselineRun": prepared.get("baselineBinding", {}).get("baselineRun") if prepared.get("baselineBinding") else None,
            "baselineSha256": prepared.get("baselineBinding", {}).get("baselineSha256") if prepared.get("baselineBinding") else None,
            "normalizedSpecSha256": hashes.get("normalized-spec.json"),
            "layoutProbe": layout,
            "layoutCheck": layout_check,
            "guardDriver": {
                "assertions": len(assertions),
                "failed": len(failed_assertions),
                "summary": driver_text.strip().splitlines()[-1] if driver_text.strip() else "",
                "instrument": "stub / guard-driver (in-process synthetic memory, NOT the game)",
            },
            "captures": sorted(p.name for p in run.glob("*.mwcap")),
            "manifests": sorted(p.name for p in run.glob("*.manifest.json")),
            "nativeArtifacts": {
                "hookReceiptDll": {"path": str(hook_dll), "exists": hook_dll.is_file(),
                                   "sha256": hashes.get("hook_receipt.dll")},
                "probeExe": {"path": str(probe_exe), "exists": probe_exe.is_file(),
                             "sha256": hashes.get("hook_receipt_probe.exe")},
                "injected": False, "launched": False,
            },
            "writesGameBytes": False,
        }
        # **哈希的自指问题**：prepared.json 里不能放它**自己**的最终 hash —— 写进去
        # 就改变内容，hash 随即变。所以 prepared.json 里记它**写入时**的 hash，并把
        # **权威 hash 表放在最后写的 build-result.json 里**（它写完之后才是最终值）。
        prepared_doc = json.loads((run / "prepared.json").read_text(encoding="utf-8-sig"))
        prepared_doc["hashesAtWrite"] = dict(hashes)
        prepared_doc["hashAuthority"] = (
            "build-result.json 的 hashes 是权威表（它是最后写的，故能含 prepared.json "
            "的最终 hash）；prepared.json 里的 hashesAtWrite 是写入当时的快照。"
        )
        (run / "prepared.json").write_text(
            json.dumps(prepared_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        hashes["prepared.json"] = _sha256_file(run / "prepared.json")
        build_result["hashes"] = hashes
        build_result["preparedSha256"] = hashes["prepared.json"]
        (run / "build-result.json").write_text(
            json.dumps(build_result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        _emit(receipt("compile-check", build_result, True))
        return 0
    except MounterError as exc:
        _emit(receipt("compile-check", {**exc.as_dict(), "run": str(run)}, False,
                      blocked="编译/探针/驱动未全过 ⇒ **没有**可派发的构建结果"))
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        _emit(receipt("compile-check", {"ok": False, "code": type(exc).__name__,
                                        "detail": str(exc), "run": str(run)}, False,
                      blocked="编译链路异常 ⇒ 没有可派发的构建结果"))
        return 1


def _layout_probe_source() -> str:
    """布局探针 TU：**包含生成物**，于是它打印的就是生成物自己的 ABI。"""
    return '''// 由 component_mounter.py --compile-check 生成。
// 只做一件事：把**编译器**对生成物 ABI 的答案打印成 JSON。
// 不派发、不注入、不碰游戏。
#include "component_mounter_native.cpp"
#include <cstdio>

int main() {
    const mt::LayoutProbe probe = mt::MakeLayoutProbe();
    std::printf("{");
    std::printf("\\"captureVersion\\":%u,", probe.captureVersion);
    std::printf("\\"captureHeaderBytes\\":%llu,", (unsigned long long)probe.captureHeaderBytes);
    std::printf("\\"offsetVersion\\":%llu,", (unsigned long long)probe.offsetVersion);
    std::printf("\\"offsetRecords\\":%llu,", (unsigned long long)probe.offsetRecords);
    std::printf("\\"offsetOwner\\":%llu,", (unsigned long long)probe.offsetOwner);
    std::printf("\\"offsetLayout\\":%llu,", (unsigned long long)probe.offsetLayout);
    std::printf("\\"recordHeaderBytes\\":%llu,", (unsigned long long)probe.recordHeaderBytes);
    std::printf("\\"magicBytes\\":%llu,", (unsigned long long)probe.magicBytes);
    std::printf("\\"wrapperBytes\\":%llu,", (unsigned long long)probe.wrapperBytes);
    std::printf("\\"setHeaderBytes\\":%llu,", (unsigned long long)probe.setHeaderBytes);
    std::printf("\\"listHeaderBytes\\":%llu,", (unsigned long long)probe.listHeaderBytes);
    std::printf("\\"slotBytes\\":%llu,", (unsigned long long)probe.slotBytes);
    std::printf("\\"ownerSetOffset\\":%llu,", (unsigned long long)probe.ownerSetOffset);
    std::printf("\\"ownerListOffset\\":%llu,", (unsigned long long)probe.ownerListOffset);
    std::printf("\\"ownerStateOffset\\":%llu,", (unsigned long long)probe.ownerStateOffset);
    std::printf("\\"arrayCountOffset\\":%llu,", (unsigned long long)probe.arrayCountOffset);
    std::printf("\\"arrayElementOffset\\":%llu,", (unsigned long long)probe.arrayElementOffset);
    std::printf("\\"wrapperKindOffset\\":%llu,", (unsigned long long)probe.wrapperKindOffset);
    std::printf("\\"wrapperConfigOffset\\":%llu,", (unsigned long long)probe.wrapperConfigOffset);
    std::printf("\\"wrapperEnabledOffset\\":%llu,", (unsigned long long)probe.wrapperEnabledOffset);
    std::printf("\\"wrapperBackrefOffset\\":%llu,", (unsigned long long)probe.wrapperBackrefOffset);
    std::printf("\\"configBackrefOffset\\":%llu,", (unsigned long long)probe.configBackrefOffset);
    std::printf("\\"configOwnerOffset\\":%llu,", (unsigned long long)probe.configOwnerOffset);
    std::printf("\\"setBucketsOffset\\":%llu,", (unsigned long long)probe.setBucketsOffset);
    std::printf("\\"setSlotsOffset\\":%llu,", (unsigned long long)probe.setSlotsOffset);
    std::printf("\\"setCountOffset\\":%llu,", (unsigned long long)probe.setCountOffset);
    std::printf("\\"setLastIndexOffset\\":%llu,", (unsigned long long)probe.setLastIndexOffset);
    std::printf("\\"setFreeHeadOffset\\":%llu,", (unsigned long long)probe.setFreeHeadOffset);
    std::printf("\\"maxComponents\\":%llu,", (unsigned long long)probe.maxComponents);
    std::printf("\\"kindCount\\":%llu,", (unsigned long long)probe.kindCount);
    std::printf("\\"componentRowBytes\\":%llu,", (unsigned long long)probe.componentRowBytes);
    std::printf("\\"mountResultBytes\\":%llu,", (unsigned long long)probe.mountResultBytes);
    std::printf("\\"snapshotBytes\\":%llu,", (unsigned long long)probe.snapshotBytes);
    std::printf("\\"captureSinkBytes\\":%llu,", (unsigned long long)probe.captureSinkBytes);
    std::printf("\\"kindRunLedgerEmpty\\":%s", probe.kindRunLedgerEmpty ? "true" : "false");
    std::printf("}\\n");
    return 0;
}
'''


#: 布局探针 JSON 里必须出现、且必须等于本文件声明的值。
LAYOUT_PROBE_EXPECTED: dict[str, int] = {
    "captureVersion": CAPTURE_VERSION,
    "captureHeaderBytes": CAPTURE_HEADER_OFFSETS["kCaptureHeaderBytes"],
    "offsetVersion": CAPTURE_HEADER_OFFSETS["kCaptureOffsetVersion"],
    "offsetRecords": CAPTURE_HEADER_OFFSETS["kCaptureOffsetRecords"],
    "offsetOwner": CAPTURE_HEADER_OFFSETS["kCaptureOffsetOwner"],
    "offsetLayout": CAPTURE_HEADER_OFFSETS["kCaptureOffsetLayout"],
    "recordHeaderBytes": 12,
    "magicBytes": 8,
    "wrapperBytes": CAPTURE_LAYOUT["kWrapperBytes"],
    "setHeaderBytes": CAPTURE_LAYOUT["kSetHeaderBytes"],
    "listHeaderBytes": CAPTURE_LAYOUT["kListHeaderBytes"],
    "slotBytes": CAPTURE_LAYOUT["kSlotBytes"],
    "ownerSetOffset": CAPTURE_LAYOUT["kOwnerSetOffset"],
    "ownerListOffset": CAPTURE_LAYOUT["kOwnerListOffset"],
    "ownerStateOffset": CAPTURE_LAYOUT["kOwnerStateOffset"],
    "arrayCountOffset": CAPTURE_LAYOUT["kArrayHeaderCountOffset"],
    "arrayElementOffset": CAPTURE_LAYOUT["kArrayElementOffset"],
    "wrapperKindOffset": CAPTURE_LAYOUT["kWrapperKindOffset"],
    "wrapperConfigOffset": CAPTURE_LAYOUT["kWrapperConfigOffset"],
    "wrapperEnabledOffset": CAPTURE_LAYOUT["kWrapperEnabledOffset"],
    "wrapperBackrefOffset": CAPTURE_LAYOUT["kWrapperBackrefOffset"],
    "configBackrefOffset": CAPTURE_LAYOUT["kConfigBackrefOffset"],
    "configOwnerOffset": CAPTURE_LAYOUT["kConfigOwnerOffset"],
    "setBucketsOffset": CAPTURE_LAYOUT["kSetBucketsOffset"],
    "setSlotsOffset": CAPTURE_LAYOUT["kSetSlotsOffset"],
    "setCountOffset": CAPTURE_LAYOUT["kSetCountOffset"],
    "setLastIndexOffset": CAPTURE_LAYOUT["kSetLastIndexOffset"],
    "setFreeHeadOffset": CAPTURE_LAYOUT["kSetFreeHeadOffset"],
    "maxComponents": CAPTURE_LAYOUT["kMaxComponents"],
    "kindCount": len(DEFAULT_EXECUTABLE_KINDS),
    # ComponentRow = 4*uint64 + int32 + uint8 + 3 pad = 40。**不要手算**：
    # 这个值曾经被手写成 56，是布局探针把它抓出来的（探针对，声明错）。
    # 现在它是**编译器答案的期望值**，而真正的答案仍以 receipt_layout_probe.exe 的输出为准。
    "componentRowBytes": 40,
}


def _check_layout(layout: dict, *, expected_kind_count: int | None = None) -> dict:
    """编译器给的数字必须与本文件声明的**完全一致**；不一致即具名拒绝。

    ``expected_kind_count`` 必须由调用方按**本次 run 的 kind 表**给出：
    ``--kinds`` 收窄后 kind 表会变小，拿默认 45 去比会误判（实测踩过）。
    """
    if not isinstance(layout, dict):
        raise MounterError("LAYOUT_PROBE_NOT_OBJECT", f"探针输出不是对象：{type(layout).__name__}")
    expected_set = dict(LAYOUT_PROBE_EXPECTED)
    if expected_kind_count is not None:
        expected_set["kindCount"] = int(expected_kind_count)
    drift = []
    for key, expected in expected_set.items():
        if key not in layout:
            drift.append({"field": key, "observed": None, "expected": expected, "why": "缺字段"})
            continue
        observed = layout[key]
        if isinstance(observed, bool) or not isinstance(observed, int):
            drift.append({"field": key, "observed": observed, "expected": expected,
                          "why": "不是整数"})
            continue
        if observed != expected:
            drift.append({"field": key, "observed": observed, "expected": expected,
                          "why": "编译器答案与本文件声明不符"})
    # 与 readback.py 的冻结布局交叉核对（读回按它自己的常量重走结构）。
    readback_path = Path(__file__).with_name("readback.py")
    readback_agree = None
    if readback_path.is_file():
        text = readback_path.read_text(encoding="utf-8")
        readback_agree = bool(
            f"CAPTURE_HEADER_BYTES = {CAPTURE_HEADER_OFFSETS['kCaptureHeaderBytes']}" in text
            and f"CAPTURE_OFFSET_LAYOUT = {CAPTURE_HEADER_OFFSETS['kCaptureOffsetLayout']}" in text
        )
    if drift:
        raise MounterError(
            "LAYOUT_PROBE_DRIFT",
            "布局探针与声明不符：" + "; ".join(
                f"{d['field']} observed={d['observed']} expected={d['expected']}" for d in drift[:6]
            ),
        )
    return {
        "ok": True,
        "checkedFields": len(expected_set),
        "drift": [],
        "readbackFrozenLayoutAgrees": readback_agree,
        "note": "探针数字来自**编译器**（sizeof/常量），不是本文件手抄；readback.py 独立冻结同一组数字。",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_kinds(text: str | None) -> tuple[int, ...]:
    if not text:
        return DEFAULT_EXECUTABLE_KINDS
    out: list[int] = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk, 16) if chunk.lower().startswith("0x") else int(chunk)
        except ValueError:
            raise MounterError("BAD_KIND_ARGUMENT", f"--kinds 里的 {chunk!r} 不是整数") from None
        out.append(value)
    if not out:
        raise MounterError("BAD_KIND_ARGUMENT", "--kinds 给了但解析出空集合")
    return tuple(sorted(set(out)))


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_resolve(args) -> int:
    try:
        result = resolve_anchors(
            image_path=Path(args.image),
            require=tuple(args.require.split(",")),
            allow_rva_literals=bool(args.allow_rva_literals),
        )
    except MounterError as exc:
        _emit(receipt("resolve-anchors", exc.as_dict(), False,
                      blocked="锚点未解析 ⇒ 不产出 TU、不发出任何请求（fail-closed）"))
        return 1
    _emit(receipt("resolve-anchors", result, True))
    return 0


def cmd_emit_tu(args) -> int:
    try:
        anchors, _, _ = load_runtime_anchors()
        kinds = _parse_kinds(args.kinds)
        for kind in kinds:
            require_executable_kind(kind, kinds)
        resolved = resolve_anchors(image_path=Path(args.image), require=("ATTACH",))
        written = write_native_sources(Path(args.out), anchors=anchors, kinds=kinds)
    except MounterError as exc:
        _emit(receipt("emit-tu", exc.as_dict(), False,
                      blocked="锚点/kind 闸未过 ⇒ **没有**写任何 TU"))
        return 1
    written["anchors"] = resolved["anchors"]
    written["checks"] = resolved["checks"]
    written["kinds"] = list(kinds)
    written["kindNames"] = {str(k): component_kind_name(k) for k in kinds}
    written["kindRunLedger"] = {str(k): v for k, v in KIND_RUN_LEDGER.items()}
    _emit(receipt("emit-tu", written, True))
    return 0


def cmd_check_deps(args) -> int:
    tree = dependency_tree()
    _emit(receipt("check-deps", tree, bool(tree["ok"])))
    return 0 if tree["ok"] else 1


def _strip_cpp_literals(text: str) -> str:
    """去掉字符串/字符字面量内容，保留其它字符（长度不变，便于报行号）。

    括号配平检查必须在**去字面量之后**做：manifest 生成代码里有 ``\\"rows\\": [``
    这类字符串，里面的括号是数据不是代码 —— 直接数全文括号会误报。
    """
    out = list(text)
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == '"':
            index += 1
            while index < length:
                if text[index] == "\\":
                    out[index] = " "
                    index += 1
                    if index < length:
                        out[index] = " "
                        index += 1
                    continue
                if text[index] == '"':
                    break
                out[index] = " "
                index += 1
        elif ch == "'":
            index += 1
            while index < length:
                if text[index] == "\\":
                    out[index] = " "
                    index += 1
                    if index < length:
                        out[index] = " "
                        index += 1
                    continue
                if text[index] == "'":
                    break
                out[index] = " "
                index += 1
        elif ch == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                out[index] = " "
                index += 1
            continue
        index += 1
    return "".join(out)


def _balance_problems(label: str, text: str) -> list[str]:
    code = _strip_cpp_literals(text)
    problems = []
    for open_ch, close_ch in (("{", "}"), ("(", ")"), ("[", "]")):
        if code.count(open_ch) != code.count(close_ch):
            problems.append(f"{label}:{open_ch}{close_ch}={code.count(open_ch)}/{code.count(close_ch)}")
    return problems


def cmd_selftest(args) -> int:
    """自检必须 **fail-closed**：不确定即失败（contract v26 moduleSelfCheckPolicy）。"""
    checks: list[dict] = []

    def note(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1) 本文件可编译（不是「已 import」，是 compile()）。
    source = Path(__file__).read_text(encoding="utf-8")
    try:
        compile(source, str(Path(__file__)), "exec")
        note("python_compiles", True, "compile() 通过")
    except SyntaxError as exc:  # pragma: no cover
        note("python_compiles", False, f"SyntaxError: {exc}")

    # 2) 枚举宽度与哨兵。
    real = [v for v in COMPONENT_KINDS.values() if v != KIND_SENTINEL]
    note("enum_members_46", len(COMPONENT_KINDS) == 46, f"成员数={len(COMPONENT_KINDS)}")
    note("enum_real_45", len(real) == 45 and len(set(real)) == 45,
         f"真成员={len(real)} 去重={len(set(real))}")
    note("drop_stuff_is_37", COMPONENT_KINDS["BeyondCompTypeDropStuff"] == 37, "kind 37")
    note("sentinel_is_47", KIND_SENTINEL == 47, "Arraysize=47")

    # 3) kind 闸：哨兵 / 未知 / 域外 三态。
    gate: dict[str, str] = {}
    for label, value in (("sentinel", KIND_SENTINEL), ("unknown", 9999),
                         ("not_in_set", 17)):
        try:
            require_executable_kind(value, [37])
            gate[label] = "NO_REFUSAL"
        except MounterError as exc:
            gate[label] = exc.code
    note("gate_sentinel", gate["sentinel"] == "sentinel_is_not_a_component", gate["sentinel"])
    note("gate_unknown", gate["unknown"] == "unknown_component_kind", gate["unknown"])
    note("gate_not_in_set", gate["not_in_set"] == "kind_not_in_executable_set", gate["not_in_set"])
    note("gate_accepts_37", require_executable_kind(37, [37]) == 37, "37 在集合里则通过")

    # 4) 锚点：真镜像上必须**通过**；缺锚点/丢 head32 必须**拒绝**。
    profile_ok = False
    profile_detail = ""
    try:
        anchors, _, _ = load_runtime_anchors()
        profile_ok = "ATTACH" in anchors
        profile_detail = f"ATTACH rva=0x{anchors['ATTACH'].rva:x}" if profile_ok else "ATTACH 缺失"
    except MounterError as exc:
        profile_detail = f"{exc.code}: {exc.detail}"
    note("anchor_present_in_profile", profile_ok, profile_detail)

    resolved_ok = False
    resolved_detail = ""
    if DEFAULT_IMAGE.is_file():
        try:
            resolved = resolve_anchors()
            resolved_ok = True
            resolved_detail = (
                f"image_sha256={resolved['imageSha256'][:16]}… "
                f"head32Equal={resolved['checks'][0]['head32Equal']}"
            )
        except MounterError as exc:
            resolved_detail = f"{exc.code}: {exc.detail}"
    else:
        resolved_detail = f"磁盘镜像不存在：{DEFAULT_IMAGE}（锚点无法复核到构建）"
    note("anchor_resolves_against_disk_image", resolved_ok, resolved_detail)

    literal_refused = False
    literal_detail = ""
    if DEFAULT_IMAGE.is_file():
        try:
            resolve_anchors(allow_rva_literals=True)
            literal_detail = "没有拒绝 ⇒ 闸是 fail-open 的"
        except MounterError as exc:
            literal_refused = exc.code == "ABI_ANCHOR_BUILD_DRIFT"
            literal_detail = exc.code
    else:
        literal_detail = "镜像不存在，跳过（不冒充已验证）"
        literal_refused = False
    note("negative_control_head32_dropped_is_refused", literal_refused, literal_detail)

    missing_refused = False
    missing_detail = ""
    try:
        resolve_anchors(require=("NO_SUCH_ANCHOR",))
        missing_detail = "没有拒绝 ⇒ 缺锚点闸 fail-open"
    except MounterError as exc:
        missing_refused = exc.code == "ABI_ANCHOR_NOT_DERIVED"
        missing_detail = exc.code
    note("negative_control_missing_anchor_is_refused", missing_refused, missing_detail)

    # 5) 生成物结构自检（去字面量后括号配平 + 必需符号 + 禁项）。
    tu_ok = False
    tu_detail = ""
    try:
        anchors, _, _ = load_runtime_anchors()
        tu = emit_native_tu(anchors=anchors, kinds=DEFAULT_EXECUTABLE_KINDS)
        driver = emit_driver_tu(kinds=DEFAULT_EXECUTABLE_KINDS)
        problems = _balance_problems("tu", tu) + _balance_problems("driver", driver)
        # 禁项按**代码**查（去掉字面量后再查），否则注释里提到就误报。
        for label, text in (("tu", _strip_cpp_literals(tu)),
                            ("driver", _strip_cpp_literals(driver))):
            if "native_tabs" in text or "generalized_tabs" in text:
                problems.append(f"{label}:forbidden_token")
        if '#include "' in tu:
            problems.append("tu:includes_repo_file")
        for symbol in ("MountOne", "AttachComponent", "EncodeCapture", "kKindTable",
                       "attached_verified", "prefix_changed"):
            if symbol not in tu:
                problems.append(f"tu:missing_symbol:{symbol}")
        if "inline constexpr KindEntry kKindTable[]" not in tu:
            problems.append("tu:missing_kind_table_declaration")
        tu_ok = not problems
        tu_detail = "ok" if tu_ok else ";".join(problems[:6])
    except MounterError as exc:
        tu_detail = f"{exc.code}: {exc.detail}"
    note("generated_sources_structure", tu_ok, tu_detail)

    # 6) 跨文件布局一致性：**结构化**比对 —— 本文件把 CAPTURE_LAYOUT 改名成读回侧的
    #    逻辑名，再要求 readback.py 的冻结布局里每个逻辑字段都出现且是可解析的整数。
    #    （名字不同、语义相同；检查的是「读回的冻结布局覆盖了写入器写出的每一个字段」。）
    readback_path = Path(__file__).with_name("readback.py")
    layout_ok = False
    layout_detail = ""
    mapping = {
        "kOwnerClassOffset": "ownerClassOffset",
        "kOwnerSetOffset": "ownerSetOffset",
        "kOwnerListOffset": "ownerListOffset",
        "kOwnerStateOffset": "ownerStateOffset",
        "kArrayHeaderCountOffset": "arrayLengthOffset",
        "kArrayElementOffset": "arrayElementOffset",
        "kListHeaderBytes": "listHeaderBytes",
        "kSetHeaderBytes": "setHeaderBytes",
        "kSetBucketsOffset": "setBucketsOffset",
        "kSetSlotsOffset": "setSlotsOffset",
        "kSetCountOffset": "setCountOffset",
        "kSetLastIndexOffset": "setLastIndexOffset",
        "kSetFreeHeadOffset": "setFreeHeadOffset",
        "kWrapperBytes": "wrapperBytes",
        "kWrapperBackrefOffset": "wrapperBackrefOffset",
        "kWrapperConfigOffset": "wrapperConfigOffset",
        "kWrapperEnabledOffset": "wrapperEnabledOffset",
        "kWrapperKindOffset": "wrapperKindOffset",
        "kConfigBackrefOffset": "configBackrefOffset",
        "kConfigOwnerOffset": "configOwnerOffset",
        "kSlotBytes": "slotBytes",
        "kMaxComponents": "maxComponents",
    }
    if readback_path.is_file():
        try:
            # 不 import readback（保持独立）；改为解析它的 FROZEN_LAYOUTS 文本块。
            text = readback_path.read_text(encoding="utf-8")
            start = text.index("FROZEN_LAYOUTS")
            end = text.index("\n}\n", start)
            block = text[start:end]
            missing = [dst for dst in mapping.values() if f'"{dst}"' not in block]
            if missing:
                layout_detail = f"readback 冻结布局缺字段：{missing[:6]}"
            else:
                literal_mismatch = []
                for src, dst in mapping.items():
                    # readback 冻结布局里的数值写成字面量；十六进制与十进制两种写法都接受。
                    value = CAPTURE_LAYOUT[src]
                    forms = (f'"{dst}": 0x{value:X}', f'"{dst}": {value}')
                    if not any(form in block for form in forms):
                        literal_mismatch.append(
                            f"{src}=0x{value:X} 未在 readback[{dst}] 里出现")
                # MWCAP 头部偏移必须与 readback 的 CAPTURE_OFFSET_* 逐字节一致。
                for name, value in CAPTURE_HEADER_OFFSETS.items():
                    if name == "kCaptureHeaderBytes":
                        if f"CAPTURE_HEADER_BYTES = {value}" not in text:
                            literal_mismatch.append(f"CAPTURE_HEADER_BYTES != {value}")
                        continue
                    const = name.replace("kCaptureOffset", "CAPTURE_OFFSET_").upper()
                    if f"{const} = {value}" not in text:
                        literal_mismatch.append(f"{const} != {value}")
                layout_ok = not literal_mismatch
                layout_detail = "ok" if layout_ok else "; ".join(literal_mismatch[:6])
        except (OSError, ValueError) as exc:
            layout_detail = f"{type(exc).__name__}: {exc}"
    else:
        layout_detail = "readback.py 不存在"
    note("readback_layout_covers_writer_layout", layout_ok, layout_detail)

    ok = all(item["ok"] for item in checks)
    _emit(receipt("selftest", {
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "total": len(checks),
        "kindRunLedger": {str(k): v for k, v in KIND_RUN_LEDGER.items()},
        "honestLimits": [
            "自检**不是**通过证据（world-contract v26 moduleSelfCheckPolicy）；它只回答"
            "「本文件与生成物在静态层面是否自洽」。",
            "本文件没有、也不能证明「游戏里挂得上」：那需要 leader 的独占原生窗口。",
            "KIND_RUN_LEDGER 为空 ⇒ 本模块**没有任何 kind** 在真实引擎里被跑过。",
        ],
    }, ok))
    return 0 if ok else 1


class _ReceiptingParser(argparse.ArgumentParser):
    """命令行用法错误也要**带 code 进回执**。

    默认的 ``ArgumentParser.error`` 直接 ``sys.exit(2)`` 到 stderr ⇒ 调用方拿不到
    任何结构化 code（实测：多余的参数会得到空 stdout + exit 2，看起来像"没报错"）。
    """

    def error(self, message: str):  # type: ignore[override]
        raise MounterError("CLI_USAGE_ERROR", f"{message}；usage: {self.format_usage().strip()}")


def build_parser() -> argparse.ArgumentParser:
    parser = _ReceiptingParser(
        prog="component_mounter.py",
        description=(
            "combat-encounters 原生挂载写入器：锚点 fail-closed 解析 + 生成可编译的"
            "挂载 TU（真实调用 attach）+ MWCAP 原始转储。开发期零游戏写入。"
        ),
    )
    parser.add_argument("--image", default=str(DEFAULT_IMAGE),
                        help=f"目标镜像（只读，仅用于锚点复核）；默认 {DEFAULT_IMAGE}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("resolve-anchors", help="只解析并复核锚点（不写任何东西）")
    p.add_argument("--require", default="ATTACH", help="逗号分隔的锚点名，默认 ATTACH")
    p.add_argument("--allow-rva-literals", action="store_true",
                   help="反向控制：丢掉 head32 后必须失败。生产路径永远不要用。")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("emit-tu", help="复核锚点后写出 C++ TU + 驱动")
    p.add_argument("--out", required=True, help="输出目录（工程内）")
    p.add_argument("--kinds", default=None,
                   help="逗号分隔的 kind 白名单；默认 45 项真成员")
    p.set_defaults(func=cmd_emit_tu)

    p = sub.add_parser("check-deps", help="依赖树实测（含 sha256 与「有没有改过共享原语」）")
    p.set_defaults(func=cmd_check_deps)

    p = sub.add_parser("prepare", help="生成一次性候选目录（隔离 source copy + target_config + 固定 hook/probe/wrapper）")
    p.add_argument("--kinds", default=None, help="逗号分隔的 kind 白名单；默认 45 项真成员")
    p.add_argument("--root", default=None,
                   help="**仅用于本地验证**：覆盖固定根（默认 "
                        f"{FIXED_ROOT.as_posix()}）。覆盖会写进回执的 rootPolicy。")
    p.add_argument("--session", default=None,
                   help="真实 TargetProcess 身份 JSON（native_profiles.query_identity 留档）")
    p.add_argument("--discover-session", action="store_true",
                   help="现读目标会话（native_profiles.discover_session + validate_session）；只读")
    p.add_argument("--compile-placeholder", action="store_true",
                   help="无真实会话时只编译：identityPlaceholder=true，产物**不可派发**")
    p.add_argument("--synthetic-session-for-compile-only", action="store_true",
                   help="配 --compile-placeholder：写入**醒目合成**身份（0x5EED…），"
                        "只为让共享探针的 fail-closed static_assert 通过从而验证补丁"
                        "**可编译**；回执标 syntheticSession=true，强制不可派发")
    p.add_argument("--deadline-seconds", type=int, default=600,
                   help="deadline 秒数（基于 GetTickCount64）；默认 600")
    p.add_argument("--allow-unverified-kinds", action="store_true",
                   help="显式放行未经 owner/class/fields 核实的 kind（回执标 "
                        "evidenceGateBypassed）；生产路径不要用")
    p.add_argument("--baseline", default=None,
                   help="只读基线 run 目录（身份宿主入口；提供后写进 prepared.json 的 "
                        "baselineBinding）")
    p.add_argument("--spec", default=None,
                   help="规范化宿主 kind 配置 JSON（身份宿主入口；每个 kind 的 "
                        "owner/class/fields 必须显式给出）")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("compile-check", help="对候选做编译布局探针 + 守卫驱动 + hook DLL/probe（只编译，不派发）")
    p.add_argument("--run", required=True, help="prepare 产出的候选目录")
    p.add_argument("--require-launchable", action="store_true",
                   help="要求产物可派发；缺真实会话/baseline/spec 时**具名 fail-closed**"
                        "（不接受用编译占位换取 launchable）")
    p.set_defaults(func=cmd_compile_check)

    p = sub.add_parser("selftest", help="fail-closed 自检（不是通过证据）")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser(
        "graph-check",
        help="默认图**无悬空节点**判定（含 --self-test 的正面/反面控制）")
    p.add_argument("--plan", default="data/mondstadt/combat/combat-graph-default.json",
                   help="默认图文件（默认 data/mondstadt/combat/combat-graph-default.json）")
    p.add_argument("--self-test", action="store_true",
                   help="跑两条控制：①故意插孤点必须被抓 ②把 725[3:1] 接上必须报 type-27")
    p.set_defaults(func=cmd_graph_check)

    p = sub.add_parser(
        "mount-plan",
        help="挂载与字段配置计划（**执行字段写入闸门**，不过则具名拒绝）")
    p.add_argument("--kind-fields", default=None,
                   help="kind 解析文件（默认 data/mondstadt/combat/kind-field-resolutions.json）")
    p.add_argument("--candidate", default=None,
                   help="生产候选（默认 data/mondstadt/combat/production-candidate.json）")
    p.set_defaults(func=cmd_mount_plan)

    p = sub.add_parser(
        "override-card",
        help="产出**可调用 native 覆盖卡**（含 argv + 实际 dispatch + readback 协议）")
    p.add_argument("--run", required=True, help="prepare 出来的 run 目录")
    p.add_argument("--camp", default=None, help="只出某个营地（camp-a/camp-b/camp-c）")
    p.add_argument("--out", default=None, help="卡片落盘路径（默认 <run>/override-card.json）")
    p.set_defaults(func=cmd_override_card)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # **parse_args 必须在 try 里**：否则用法错误会死在 main 之外、拿不到结构化 code。
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except MounterError as exc:
        _emit(receipt("error", exc.as_dict(), False))
        return 2
    except subprocess.TimeoutExpired as exc:
        # 真 API 错误：编译超时。**带具体 code 与实测秒数**进回执，不吞。
        _emit(receipt("error", {
            "ok": False,
            "code": "COMPILE_TIMEOUT",
            "detail": f"{exc.cmd if isinstance(exc.cmd, str) else ' '.join(exc.cmd or [])}"
                      f" 超过 {exc.timeout} 秒未完成",
            "timeoutSeconds": exc.timeout,
        }, False))
        return 2
    except PermissionError as exc:
        # 真 API 错误：文件权限。带回 winerror 便于定位沙箱/ACL。
        _emit(receipt("error", {
            "ok": False,
            "code": "OS_PERMISSION_DENIED",
            "detail": f"{exc.filename}: {exc.strerror}",
            "winerror": getattr(exc, "winerror", None),
            "errno": exc.errno,
            "path": exc.filename,
        }, False))
        return 2
    except OSError as exc:
        _emit(receipt("error", {
            "ok": False,
            "code": "OS_ERROR",
            "detail": f"{type(exc).__name__}: {exc}",
            "winerror": getattr(exc, "winerror", None),
            "errno": exc.errno,
            "path": getattr(exc, "filename", None),
        }, False))
        return 2
    except json.JSONDecodeError as exc:
        _emit(receipt("error", {
            "ok": False,
            "code": "JSON_INVALID",
            "detail": f"{exc.doc[:80]!r} 第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
            "line": exc.lineno,
            "column": exc.colno,
        }, False))
        return 2
    except Exception as exc:  # noqa: BLE001 - **兜底也必须带 code**，绝不裸抛 traceback
        _emit(receipt("error", {
            "ok": False,
            "code": f"UNHANDLED:{type(exc).__name__}",
            "detail": str(exc)[:800],
            "tracebackTail": traceback.format_exc()[-1200:],
        }, False))
        return 3


if __name__ == "__main__":  # pragma: no cover - manual/runner entry
    raise SystemExit(main())
