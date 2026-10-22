#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成千星沙箱「最简平台跳跃挑战」离线资产包（GIA）。

设计约束（本工程自定，不来自上游）：
  * 仅使用 Python 标准库，纯离线，不读写游戏存档、不调用游戏、不联网。
  * 只做静态方块实体的编码，不含节点图、不含结算逻辑。
  * 输出为「离线可解析的候选资产包」，是否被游戏接受由后续真实导入验收判定。

格式依据（字段号是格式事实，代码为本工程独立实现，未复制上游源码）：
  * GIA 外壳：24 字节包装（20 字节头 + 4 字节尾魔数），依据
    .runtime/research-sources/file-formats/evidence/evidence.json 的 sample.gia 实测，
    以及 docs 里对 GIA 的说明。
  * 载荷：GIACollection / Asset / Entity 字段号依据
    .runtime/research-sources/file-formats/UGC-Gia-Gil-ProtoBuf/*.proto
    （MIT，https://github.com/luern0313/UGC-Gia-Gil-ProtoBuf）。
  * 模板 ID：依据 third_party/UGC-File-Generate-Utils/
    config/block_config.py（Apache-2.0，https://github.com/luern0313/UGC-File-Generate-Utils）
    里列出的真实内建方块模板 ID，均为 size_units=1.0，故 scale 即游戏单位尺寸。

用法：
    python mvp/generate_mvp.py                  # 生成到 mvp/build/
    python mvp/generate_mvp.py --out <目录>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---- GIA 文件外壳常量（来自 evidence/sample.gia 实测 + 文档） ----
HEAD_MAGIC = 0x00000326
TAIL_MAGIC = 0x00000679
FILE_VERSION = 1
FILE_TYPE_GIA = 3
HEADER_SIZE = 20
TAIL_SIZE = 4

# ---- protobuf 字段号（来自 UGC-Gia-Gil-ProtoBuf/*.proto） ----
F_GIACOLLECTION_ASSETS = 1
F_ASSET_META, F_ASSET_NAME, F_ASSET_TYPE, F_ASSET_ENTITY = 1, 3, 5, 12
F_META_FIELD2, F_META_TYPE, F_META_ASSET_ID = 2, 3, 4
F_ENTITY_DATA, F_ENTITY_FIELD2, F_ENTITY_TEMPLATE_ID = 1, 2, 4
F_EDATA_ID, F_EDATA_TEMPLATE, F_EDATA_PROPERTIES = 1, 2, 5
F_EDATA_COMPONENTS, F_EDATA_TEMPLATE_ID_REF = 6, 8
F_TEMPLATEREF_ID, F_TEMPLATEREF_FIELD2 = 1, 2
F_PROP_TYPE, F_PROP_NAME = 1, 11
F_NAMEPROP_NAME, F_NAMEPROP_STATIC = 1, 2
F_COMP_TYPE, F_COMP_TRANSFORM = 1, 11
F_TRANSFORM_POS, F_TRANSFORM_ROT, F_TRANSFORM_SCALE, F_TRANSFORM_501 = 1, 2, 3, 501

PROP_TYPE_NAME = 1
NAMEPROP_STATIC = 1
COMP_TYPE_TRANSFORM = 1
ASSET_TYPE_ENTITY = 3
META_TYPE_ENTITY = 2
TRANSFORM_FIELD_501 = 4294967295  # -1 as uint32

# ---- 向量分量的 wire 存在性策略（显式命名；不得凭 proto3 一般规则推断业务默认值） ----
#: proto3 隐式存在性下 float 取格式默认值 0.0 时**不写 wire**。这是**格式固有行为**，
#: 不是任何「业务默认值」声明。因此对 Scale 而言，wire 上的「分量缺失」在格式层读回 0.0，
#: 而「显式写了 0.0」与「没写」在该格式下**本就不可区分**（信息在编码时就丢了）。
VEC3_ZERO_COMPONENT_POLICY = "omit-zero-component"

#: 但**子消息本身必须始终写出**（哪怕载荷为空）。否则「整个 scale 消息缺失」与
#: 「显式 scale=(0,0,0)」在 wire 上：前者无字段标签、后者有 `1a 00`，二者可区分。
#: 旧读回实现把「无字段标签」猜成 1.0，正是本任务要修掉的静默回填。
VEC3_SUBMESSAGE_ALWAYS_PRESENT = True


def vec3_wire_presence(x: float, y: float, z: float) -> list[bool]:
    """预测 `_vec3` 会为哪几个分量写出 wire 字段（等价于「该分量是否非零」）。

    纯函数，不改任何字节输出，供测试与审计使用。
    """
    return [float(v) != 0.0 for v in (x, y, z)]


def assert_vector_presence_invariants() -> None:
    """编码器存在性不变量自检，失败抛 `AssertionError`。

    断言的都是**本工程编码器自身可判定的性质**，不涉及游戏/编辑器行为：
      1. `_vec3(0,0,0)` 载荷为空（proto3 隐式存在性，格式固有行为）；
      2. 但 scale 字段的标签与零长前缀**仍被写出**，故「整个子消息缺失」与
         「显式零向量」在 wire 上可区分；
      3. 非零分量必定上 wire（否则会静默丢数据）。
    """
    empty = _vec3(0.0, 0.0, 0.0)
    assert empty == b"", "零向量载荷应为空（proto3 隐式存在性）"
    tag = (F_TRANSFORM_SCALE << 3) | 2
    field = _bytes_field(F_TRANSFORM_SCALE, empty)
    assert field == bytes([tag, 0]), (
        f"scale 子消息标签必须写出（含零长前缀），实得 {field.hex()}"
    )
    full = _bytes_field(F_TRANSFORM_SCALE, _vec3(1.0, 2.0, 3.0))
    assert len(full) > 2, "非零分量必须上 wire"
    assert vec3_wire_presence(0.0, 0.0, 0.0) == [False, False, False]
    assert vec3_wire_presence(0.0, 1.0, 2.0) == [False, True, True]
    assert vec3_wire_presence(1.0, 1.0, 1.0) == [True, True, True]
    assert vec3_wire_presence(2.5, -1.25, 4.0) == [True, True, True]


# --------------------------------------------------------------------------
# 最小 protobuf 写出器（proto3 隐式存在性：默认值不编码）
# --------------------------------------------------------------------------
def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _varint_field(field: int, value: int) -> bytes:
    return b"" if value == 0 else _tag(field, 0) + _varint(value)


def _bytes_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(payload)) + payload


def _float_field(field: int, value: float) -> bytes:
    """float32 字段。值为 0.0 时返回空（= 不写 wire），见 `VEC3_ZERO_COMPONENT_POLICY`。"""
    if value == 0.0:
        return b""
    return _tag(field, 5) + struct.pack("<f", value)


def _vec3(x: float, y: float, z: float) -> bytes:
    """Position / Rotation / Scale 三者共用 x=1,y=2,z=3 的 float32 布局。

    注意：零分量不写 wire（proto3 隐式存在性，格式固有行为）。因此该方法对
    `(0,0,0)` 返回 **空载荷**；调用方必须用一个**始终写出字段标签**的 `_bytes_field`
    把它包起来，否则「子消息缺失」与「显式零向量」将不可区分。
    `assert_vector_presence_invariants()` 守护这条不变量。
    """
    return _float_field(1, x) + _float_field(2, y) + _float_field(3, z)


# --------------------------------------------------------------------------
# 实体编码
# --------------------------------------------------------------------------
def _encode_entity(entity: dict) -> bytes:
    template_id = int(entity["template_id"])
    entity_id = int(entity["entity_id"])
    px, py, pz = (float(v) for v in entity["position"])
    rx, ry, rz = (float(v) for v in entity["rotation"])
    sx, sy, sz = (float(v) for v in entity["scale"])

    # 三个向量子消息的字段标签必须**无条件写出**（载荷允许为空）。
    # 反例：若因载荷为空而整条字段省略，则 scale=(0,0,0) 会退化成「scale 缺失」，
    # 读回端无法区分，只能靠猜（旧实现猜 1.0）——这正是本任务修掉的缺陷。
    scale_field = _bytes_field(F_TRANSFORM_SCALE, _vec3(sx, sy, sz))
    if VEC3_SUBMESSAGE_ALWAYS_PRESENT:
        assert scale_field[:1] == bytes([(F_TRANSFORM_SCALE << 3) | 2]), (
            "scale 子消息标签必须始终写出，否则「缺失」与「显式零向量」不可区分"
        )

    transform = (
        _bytes_field(F_TRANSFORM_POS, _vec3(px, py, pz))
        + _bytes_field(F_TRANSFORM_ROT, _vec3(rx, ry, rz))
        + scale_field
        + _varint_field(F_TRANSFORM_501, TRANSFORM_FIELD_501)  # 非默认值，必须出现
    )
    component = _varint_field(F_COMP_TYPE, COMP_TYPE_TRANSFORM) + _bytes_field(
        F_COMP_TRANSFORM, transform
    )

    name_prop = _bytes_field(
        F_PROP_NAME,
        _bytes_field(F_NAMEPROP_NAME, entity["name"].encode("utf-8"))
        + _varint_field(F_NAMEPROP_STATIC, NAMEPROP_STATIC),
    )
    prop = _varint_field(F_PROP_TYPE, PROP_TYPE_NAME) + name_prop

    template_ref = _varint_field(F_TEMPLATEREF_ID, template_id) + _varint_field(
        F_TEMPLATEREF_FIELD2, 1
    )

    entity_data = (
        _varint_field(F_EDATA_ID, entity_id)
        + _bytes_field(F_EDATA_TEMPLATE, template_ref)
        + _bytes_field(F_EDATA_PROPERTIES, prop)
        + _bytes_field(F_EDATA_COMPONENTS, component)
        + _varint_field(F_EDATA_TEMPLATE_ID_REF, template_id)
    )

    entity_msg = (
        _bytes_field(F_ENTITY_DATA, entity_data)
        + _varint_field(F_ENTITY_TEMPLATE_ID, template_id)
    )

    meta = (
        _varint_field(F_META_FIELD2, 1)
        + _varint_field(F_META_TYPE, META_TYPE_ENTITY)
        + _varint_field(F_META_ASSET_ID, entity_id)
    )

    return (
        _bytes_field(F_ASSET_META, meta)
        + _bytes_field(F_ASSET_NAME, entity["name"].encode("utf-8"))
        + _varint_field(F_ASSET_TYPE, ASSET_TYPE_ENTITY)
        + _bytes_field(F_ASSET_ENTITY, entity_msg)
    )


def build_payload(entities: list[dict]) -> bytes:
    return b"".join(_bytes_field(F_GIACOLLECTION_ASSETS, _encode_entity(e)) for e in entities)


def wrap_gia(payload: bytes) -> bytes:
    """24 字节包装：file_size = 总长-4；content_length = 总长-24。

    注意：GIA 外壳的 5 个头部字段与尾魔数都是 **大端序**（`>5I`）。
    依据：evidence/sample.gia 首四字节为 00 00 00 9E（=158，大端），
    且上游 auto-miliastra core/gi_file.py 与 verify_formats.py 均使用 `struct.unpack(">5I", ...)`。
    这里若误用小端会写出自洽但错误的文件，故显式断言。
    """
    total = HEADER_SIZE + len(payload) + TAIL_SIZE
    header = struct.pack(
        ">5I", total - 4, FILE_VERSION, HEAD_MAGIC, FILE_TYPE_GIA, total - HEADER_SIZE - TAIL_SIZE
    )
    tail = struct.pack(">I", TAIL_MAGIC)
    assert struct.unpack(">5I", header) == (
        total - 4,
        FILE_VERSION,
        HEAD_MAGIC,
        FILE_TYPE_GIA,
        total - HEADER_SIZE - TAIL_SIZE,
    ), "GIA 外壳字节序自检失败"
    return header + payload + tail


# --------------------------------------------------------------------------
# 布局校验：几何必须真的能跳过去
# --------------------------------------------------------------------------
def layout_report(scene: dict) -> tuple[list[dict], list[str]]:
    c = scene["constraints"]
    tol = float(c["tolerance"])
    entities = sorted(scene["entities"], key=lambda e: float(e["position"][0]))
    rows, errors = [], []

    for prev, cur in zip(entities, entities[1:]):
        p_half = float(prev["scale"][0]) / 2.0
        c_half = float(cur["scale"][0]) / 2.0
        right_edge = float(prev["position"][0]) + p_half
        left_edge = float(cur["position"][0]) - c_half
        gap = left_edge - right_edge
        p_top = float(prev["position"][1]) + float(prev["scale"][1]) / 2.0
        c_top = float(cur["position"][1]) + float(cur["scale"][1]) / 2.0
        step = c_top - p_top

        ok_gap = (c["horizontal_gap_min"] - tol) <= gap <= (c["horizontal_gap_max"] + tol)
        ok_step = (c["step_up_min"] - tol) <= step <= (c["step_up_max"] + tol)
        if not ok_gap:
            errors.append(f"{prev['name']} -> {cur['name']}: 水平间隙 {gap:.4f} 超出允许范围")
        if not ok_step:
            errors.append(f"{prev['name']} -> {cur['name']}: 高差 {step:.4f} 超出允许范围")

        rows.append(
            {
                "from": prev["name"],
                "to": cur["name"],
                "horizontal_gap": round(gap, 6),
                "vertical_step": round(step, 6),
                "gap_ok": ok_gap,
                "step_ok": ok_step,
            }
        )

    goal = next((e for e in entities if e.get("role") == "goal"), None)
    if goal is None:
        errors.append("缺少 role=goal 的终点实体")
    else:
        tops = [
            float(e["position"][1]) + float(e["scale"][1]) / 2.0
            for e in entities
            if e is not goal
        ]
        goal_top = float(goal["position"][1]) + float(goal["scale"][1]) / 2.0
        if max(tops) >= goal_top:
            errors.append("终点平台不是最高处，胜利条件不成立")

    return rows, errors


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="生成最简平台跳跃 MVP 的 GIA 资产包")
    ap.add_argument("--scene", default=str(HERE / "scene.json"))
    ap.add_argument("--out", default=str(HERE / "build"))
    args = ap.parse_args()

    scene_path = Path(args.scene).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = json.loads(scene_path.read_text(encoding="utf-8"))

    # 模板必须有真实来源：scene.json 的 templates 表里登记过才允许使用
    for e in scene["entities"]:
        key = str(int(e["template_id"]))
        if key not in scene["templates"]:
            print(f"[FAIL] 模板 ID {key} 未在 scene.json 的 templates 中登记来源", file=sys.stderr)
            return 2

    rows, errors = layout_report(scene)
    if errors:
        for err in errors:
            print(f"[FAIL] 布局校验: {err}", file=sys.stderr)
        return 3

    entities = []
    next_id = int(scene["entity_id_start"])
    for e in scene["entities"]:
        entities.append(
            {
                "name": e["name"],
                "template_id": int(e["template_id"]),
                "position": [float(v) for v in e["position"]],
                "rotation": [float(v) for v in e["rotation"]],
                "scale": [float(v) for v in e["scale"]],
                "entity_id": next_id,
            }
        )
        next_id += 1

    payload = build_payload(entities)
    blob = wrap_gia(payload)
    gia_path = out_dir / "platformer_min.gia"
    gia_path.write_bytes(blob)

    manifest = {
        "schema": "miliastra-mvp-manifest/1",
        "scene_id": scene["scene_id"],
        "artifact": {"path": gia_path.name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()},
        "payload": {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
        "header": {
            "bytes": HEADER_SIZE,
            "file_size_field": len(blob) - 4,
            "version": FILE_VERSION,
            "head_magic": f"0x{HEAD_MAGIC:08x}",
            "file_type": FILE_TYPE_GIA,
            "content_length_field": len(payload),
            "invariant": "file_size = total-4; content_length = total-24",
        },
        "sources": {
            "scene_json_sha256": sha256_file(scene_path),
            "generator_sha256": sha256_file(Path(__file__).resolve()),
        },
        "entity_count": len(entities),
        "template_ids": sorted({e["template_id"] for e in entities}),
        "entity_ids": [e["entity_id"] for e in entities],
        "entities": entities,
        "layout_checks": rows,
        "notes": [
            "坐标以 float32 写入，scene.json 中的十进制小数 (如 0.4/1.2/3.7) 在二进制下不精确，读回比较需容差。",
            "本文件描述离线产物本身，不代表游戏已接受或已通关。",
            "向量存在性策略：零分量不写 wire（proto3 隐式存在性，格式固有行为），"
            "但 position/rotation/scale 三个子消息的字段标签无条件写出，"
            "故「子消息缺失」与「显式零向量」在 wire 上可区分；"
            "读回端对「子消息缺失」不再静默回填 1.0（见 mvp/verify_mvp.py 的 scale_state）。",
            "本清单不声称任何业务默认值：缺失分量读回为 0.0 是 proto3 格式默认，"
            "不等于游戏/编辑器对该实体的实际解释。",
        ],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] 实体 {len(entities)} 个 -> {gia_path}")
    print(f"     bytes={len(blob)} payload={len(payload)} sha256={manifest['artifact']['sha256']}")
    for r in rows:
        print(
            f"     {r['from']} -> {r['to']}: gap={r['horizontal_gap']:.3f} step={r['vertical_step']:.3f}"
        )
    print(f"[OK] manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
