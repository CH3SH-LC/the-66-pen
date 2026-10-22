#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读回校验 mvp/build/platformer_min.gia。

两条互不依赖的读回路径：
  A. 上游真实解析器：auto-miliastra 的 miliastra_agent.parsers.entities.parse_gia_payload
     （用已提交的 proto_gen pb2 反序列化），需要把该仓库 src 加入 sys.path。
  B. 本工程独立解码器：纯标准库按字段号手工解析，不复用上游任何代码。

两者结果必须一致，并且与 manifest.json / scene.json 的声明一致。

注意：本脚本只证明「离线文件可被解析且内容自洽」，
不等于游戏接受了该资产，也不等于游玩通关。

--- 向量存在性（零缩放歧义，见 CONTRACT-V07-TRANSFORM.md 的 U07） ---

proto3 隐式存在性下，float 分量取 0.0 时**不写 wire**，这是**格式固有行为**，
不是任何「业务默认值」声明。于是 scale 有三种必须在读回端分开的状态：

  1. `absent`          —— 整个 scale 子消息不在 wire 上（无字段标签）；
  2. `present_empty`   —— 子消息在 wire 上（标签 `1a 00`），无任何分量 → 格式层 (0,0,0)；
  3. `present_partial` —— 子消息在，但只有部分分量在（其余按格式默认 0.0）；
     三分量全在时为 `present_full`。

旧实现把状态 1 静默回填成 `[1.0, 1.0, 1.0]`：那是**本工程自定的业务默认值**，
不是 proto3 默认值，并使状态 1 与「显式 (1,1,1)」不可区分。
现在默认策略是 `SCALE_ABSENT_STRICT`：状态 1 读回 `scale=None` 且 `scale_state="absent"`，
**绝不静默把 0（或「未知」）变成 1**。需要旧行为的调用方须显式传
`scale_absent=SCALE_ABSENT_IDENTITY`。

**证据边界**：本文件只说明「本工程读回实现如何区分这些状态」。
游戏/编辑器对「显式零向量」与「分量缺失」的实际解释**无任何依据**，不得据此声称兼容。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

DEFAULT_UPSTREAM_SRC = (
    REPO_ROOT
    / "third_party/auto-miliastra/src"
)

HEAD_MAGIC = 0x00000326
TAIL_MAGIC = 0x00000679
TOL = 2e-5

# ---- scale 子消息缺失时的取值策略（默认绝不静默回填） ----
#: 默认：缺失即 `scale=None` + `scale_state="absent"`。不猜、不补 1.0。
SCALE_ABSENT_STRICT = "strict"
#: 兼容旧行为：缺失补 `[1.0, 1.0, 1.0]`。必须**显式**选择，且此时 `scale_state`
#: 仍为 `"absent"`，调用方可据此看出该值是补出来的。
SCALE_ABSENT_IDENTITY = "identity"
SCALE_ABSENT_POLICIES = (SCALE_ABSENT_STRICT, SCALE_ABSENT_IDENTITY)

#: 向量子消息在 wire 上的存在性状态词表（只这 4 个）。
SCALE_STATE_ABSENT = "absent"
SCALE_STATE_PRESENT_EMPTY = "present_empty"
SCALE_STATE_PRESENT_PARTIAL = "present_partial"
SCALE_STATE_PRESENT_FULL = "present_full"
SCALE_STATES = (
    SCALE_STATE_ABSENT,
    SCALE_STATE_PRESENT_EMPTY,
    SCALE_STATE_PRESENT_PARTIAL,
    SCALE_STATE_PRESENT_FULL,
)

#: `decode_payload_independent` 的实体键集：**必须**与 manifest.json 的实体键集一致
#: （`mvp/test_asset_api.py` 会断言两个集合相等），故不得新增键。
_ENTITY_KEYS = ("name", "template_id", "entity_id", "position", "rotation", "scale")

failures: list[str] = []
checks: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    checks.append({"check": name, "ok": ok, "detail": detail})
    if not ok:
        failures.append(f"{name}: {detail}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------
# 独立解码器（路径 B）
# --------------------------------------------------------------------------
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
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            value, pos = _read_varint(buf, pos)
            yield field, wt, value
        elif wt == 2:
            length, pos = _read_varint(buf, pos)
            yield field, wt, buf[pos : pos + length]
            pos += length
        elif wt == 5:
            yield field, wt, buf[pos : pos + 4]
            pos += 4
        elif wt == 1:
            yield field, wt, buf[pos : pos + 8]
            pos += 8
        else:
            raise ValueError(f"未知 wire type {wt}")


def _first(buf: bytes, field: int, wt: int):
    for f, w, v in _iter_fields(buf):
        if f == field and w == wt:
            return v
    return None


def _all(buf: bytes, field: int, wt: int) -> list:
    return [v for f, w, v in _iter_fields(buf) if f == field and w == wt]


def decode_vec3_presence(buf: bytes) -> dict:
    """解出 `x=1, y=2, z=3` 的 float32 三分量，并**逐分量**报告是否出现在 wire 上。

    返回 `{"value": [x, y, z], "present": [bool, bool, bool]}`。

    缺失分量按 **proto3 格式固有默认值 0.0** 填入 —— 这是格式行为，不是业务默认值；
    `present` 保留真相，调用方**不得**把 `present=False` 解释成任何业务默认。
    """
    value = [0.0, 0.0, 0.0]
    present = [False, False, False]
    for f, w, v in _iter_fields(buf):
        if w == 5 and 1 <= f <= 3:
            value[f - 1] = struct.unpack("<f", v)[0]
            present[f - 1] = True
    return {"value": value, "present": present}


def _vec3_state(present: list[bool] | None) -> str:
    """把逐分量存在性归到 4 值词表；`None` 表示整个子消息不在 wire 上。"""
    if present is None:
        return SCALE_STATE_ABSENT
    if all(present):
        return SCALE_STATE_PRESENT_FULL
    if not any(present):
        return SCALE_STATE_PRESENT_EMPTY
    return SCALE_STATE_PRESENT_PARTIAL


def _decode_vec3(buf: bytes) -> list[float]:
    """兼容旧私有名：只取值、不报存在性。新代码请用 `decode_vec3_presence`。"""
    return decode_vec3_presence(buf)["value"]


def decode_payload_independent_detailed(
    payload: bytes, *, scale_absent: str = SCALE_ABSENT_STRICT
) -> list[dict]:
    """存在性感知版本：在 6 键之外额外给出 `scale_state` 与逐分量存在性。

    返回的每个实体含：
      `name` / `template_id` / `entity_id` / `position` / `rotation` / `scale`
      + `scale_state`        —— 见 `SCALE_STATES` 4 值词表
      + `scale_present`      —— `[bool, bool, bool]` 或 `None`（子消息缺失）
      + `position_present` / `rotation_present` —— 同上

    `scale_absent` 见 `SCALE_ABSENT_POLICIES`：
      * `SCALE_ABSENT_STRICT`（默认）→ `scale=None`，不猜；
      * `SCALE_ABSENT_IDENTITY`      → `scale=[1.0,1.0,1.0]`，但 `scale_state` 仍为 `"absent"`。

    注意：`position`/`rotation` 缺失时填 `[0.0,0.0,0.0]`，那是 **proto3 格式默认值**，
    与业务无关；`scale` 没有格式级别的「1.0 默认」，故旧实现的 1.0 回填是工程自定行为。
    """
    if scale_absent not in SCALE_ABSENT_POLICIES:
        raise ValueError(
            f"未知 scale_absent 策略 {scale_absent!r}，只支持 {SCALE_ABSENT_POLICIES}"
        )

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
        asset_name = (_first(asset, 3, 2) or b"").decode("utf-8")

        prop_name = ""
        for prop in _all(data, 5, 2):
            if _first(prop, 1, 0) == 1:  # PropertyType.NAME
                name_prop = _first(prop, 11, 2)
                if name_prop is not None:
                    prop_name = (_first(name_prop, 1, 2) or b"").decode("utf-8")

        position = [0.0, 0.0, 0.0]
        rotation = [0.0, 0.0, 0.0]
        scale = None
        pos_present = rot_present = scl_present = None
        for comp in _all(data, 6, 2):
            if _first(comp, 1, 0) != 1:  # ComponentType.TRANSFORM
                continue
            transform = _first(comp, 11, 2)
            if transform is None:
                continue
            pos_msg = _first(transform, 1, 2)
            rot_msg = _first(transform, 2, 2)
            scl_msg = _first(transform, 3, 2)
            if pos_msg is not None:
                r = decode_vec3_presence(pos_msg)
                position, pos_present = r["value"], r["present"]
            if rot_msg is not None:
                r = decode_vec3_presence(rot_msg)
                rotation, rot_present = r["value"], r["present"]
            if scl_msg is not None:
                r = decode_vec3_presence(scl_msg)
                scale, scl_present = r["value"], r["present"]
            break

        scale_state = _vec3_state(scl_present)
        if scale is None and scale_absent == SCALE_ABSENT_IDENTITY:
            scale = [1.0, 1.0, 1.0]

        entities.append(
            {
                "name": asset_name or prop_name,
                "template_id": _first(entity_msg, 4, 0) or 0,
                "entity_id": _first(data, 1, 0) or 0,
                "position": position,
                "rotation": rotation,
                "scale": scale,
                "scale_state": scale_state,
                "scale_present": scl_present,
                "position_present": pos_present,
                "rotation_present": rot_present,
            }
        )
    return entities


def decode_payload_independent(
    payload: bytes, *, scale_absent: str = SCALE_ABSENT_STRICT
) -> list[dict]:
    """键集稳定的兼容版本：只返回 6 键，**不新增键**（`mvp/asset_api.py` 复用本函数）。

    需要存在性元数据（`scale_state` 等）请用 `decode_payload_independent_detailed`。
    """
    return [
        {k: e[k] for k in _ENTITY_KEYS}
        for e in decode_payload_independent_detailed(payload, scale_absent=scale_absent)
    ]


# --------------------------------------------------------------------------
# 上游真实解析器（路径 A）
# --------------------------------------------------------------------------
def decode_payload_upstream(payload: bytes, upstream_src: Path):
    if not upstream_src.exists():
        return None, f"上游 src 目录不存在: {upstream_src}"
    sys.path.insert(0, str(upstream_src))
    try:
        from miliastra_agent.parsers.entities import parse_gia_payload
    except Exception as exc:  # pragma: no cover - 环境相关
        return None, f"导入上游解析器失败: {exc.__class__.__name__}: {exc}"
    try:
        placements = parse_gia_payload(payload)
    except Exception as exc:  # pragma: no cover - 环境相关
        return None, f"上游解析器反序列化失败: {exc.__class__.__name__}: {exc}"
    return (
        [
            {
                "name": p.name,
                "template_id": p.template_id,
                "entity_id": p.entity_id,
                "position": [p.position.x, p.position.y, p.position.z],
                "rotation": [p.rotation.x, p.rotation.y, p.rotation.z],
                "scale": [p.scale.x, p.scale.y, p.scale.z],
            }
            for p in placements
        ],
        "",
    )


def close(a: list[float], b: list[float]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= TOL for x, y in zip(a, b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gia", default=str(HERE / "build/platformer_min.gia"))
    ap.add_argument("--manifest", default=str(HERE / "build/manifest.json"))
    ap.add_argument("--upstream-src", default=str(DEFAULT_UPSTREAM_SRC))
    args = ap.parse_args()

    gia_path = Path(args.gia)
    blob = gia_path.read_bytes()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    print(f"读回目标: {gia_path} ({len(blob)} bytes)")

    # --- 外壳（大端序，见 generate_mvp.py::wrap_gia 的说明） ---
    file_size, version, head_magic, file_type, content_length = struct.unpack(">5I", blob[:20])
    tail_magic = struct.unpack(">I", blob[-4:])[0]
    check("外壳 file_size = 总长-4", file_size == len(blob) - 4, f"{file_size} vs {len(blob) - 4}")
    check("外壳 content_length = 总长-24", content_length == len(blob) - 24, f"{content_length}")
    check("头魔数 0x00000326", head_magic == HEAD_MAGIC, hex(head_magic))
    check("尾魔数 0x00000679", tail_magic == TAIL_MAGIC, hex(tail_magic))
    check("file_type = 3 (GIA)", file_type == 3, str(file_type))
    check("version = 1", version == 1, str(version))
    check("字节序自检：小端读法必须给出无意义值", struct.unpack("<I", blob[:4])[0] != file_size,
          "防止大小端混淆再次蒙混过关")

    # --- 与上游读头实现交叉比对（防自洽错误） ---
    upstream_src_path = Path(args.upstream_src)
    if upstream_src_path.exists():
        sys.path.insert(0, str(upstream_src_path))
        try:
            from miliastra_agent.core import gi_file as _gf

            names = [n for n in dir(_gf) if not n.startswith("_")]
            print(f"      上游 gi_file 导出: {names}")
            reader = getattr(_gf, "read_header", None) or getattr(_gf, "parse_header", None)
            if reader is not None:
                h = reader(blob)
                print(f"      上游读头结果: {h}")
                # 【更正 2026-09-15】此处原为 `check("上游读头与本脚本读头一致", True)`——
                # **硬编码 True，从不比较**：执行了上游读头、打印了结果，却没有形成任何断言，
                # 于是这一项是一个**永远不会失败的 PASS**。由批次 5 的 v32b 契约（F-V32B-02）发现。
                #
                # 讽刺之处：这一项存在的理由，正是本 README 记下的那条教训——
                # 「同一人写的编码器与校验器共享错误假设时，自洽性检查无法发现问题；
                #   必须至少有一条独立于本实现的比对路径」。教训写下来了，实现它的检查却是空壳。
                #
                # 改为真比较：逐字段比对五个头部值；**任何字段取不到也判 FAIL**，
                # 不得因为「读不出来」而静默通过。
                _pairs = [("file_size", file_size), ("version", version), ("head_magic", head_magic),
                          ("file_type", file_type), ("content_length", content_length)]
                _got, _bad, _missing = {}, [], []
                for _name, _mine in _pairs:
                    _up = getattr(h, _name, None)
                    if _up is None:
                        _missing.append(_name)
                    else:
                        _got[_name] = _up
                        if _up != _mine:
                            _bad.append(f"{_name}: 上游 {_up} vs 本脚本 {_mine}")
                if _missing:
                    check("上游读头与本脚本读头一致", False,
                          f"上游读头缺少字段 {_missing}（无法比较，不判通过）")
                elif _bad:
                    check("上游读头与本脚本读头一致", False, "; ".join(_bad))
                else:
                    check("上游读头与本脚本读头一致", True,
                          "五个头部字段逐项相等：" + ", ".join(f"{k}={v}" for k, v in _got.items()))
            else:
                check("上游读头函数可定位", False, "未找到 read_header/parse_header")
        except Exception as exc:
            check("上游读头交叉比对", False, f"{exc.__class__.__name__}: {exc}")
    check("content_length 与载荷实长一致", content_length == len(blob) - 24)

    payload = blob[20:-4]

    # --- manifest 哈希 ---
    check("载荷 sha256 与 manifest 一致",
          hashlib.sha256(payload).hexdigest() == manifest["payload"]["sha256"])
    check("整文件 sha256 与 manifest 一致",
          hashlib.sha256(blob).hexdigest() == manifest["artifact"]["sha256"])

    # --- 路径 B：独立解码 ---
    print("\n路径 B — 本工程独立解码器")
    detailed = decode_payload_independent_detailed(payload)  # 默认 strict：缺失 scale 不回填
    independent = [{k: e[k] for k in _ENTITY_KEYS} for e in detailed]
    expected = manifest["entities"]
    check("实体数量 = 6", len(independent) == 6, f"实得 {len(independent)}")
    check("实体数量与 manifest 一致", len(independent) == len(expected))
    check("实体数量与 scene.json 一致",
          len(independent) == len(json.loads((HERE / "scene.json").read_text(encoding="utf-8"))["entities"]))

    # --- 存在性检查（U07）：结论来自 wire 上的字段存在性，不是「值相等」推出来的 ---
    states = [e["scale_state"] for e in detailed]
    dist = {s: states.count(s) for s in sorted(set(states))}
    print(f"      scale 存在性状态分布: {dist}")
    for e in detailed:
        print(f"        {e['name']}: state={e['scale_state']} "
              f"present={e['scale_present']} value={e['scale']}")
    absent_names = [e["name"] for e in detailed if e["scale_state"] == SCALE_STATE_ABSENT]
    check("无实体发生 scale 子消息缺失（缺失不再静默回填 1.0）", not absent_names,
          f"缺失实体={absent_names}；旧实现会把它们读成 [1.0,1.0,1.0]")

    ok_all = True
    for got, want in zip(detailed, expected):
        if got["scale"] is None:
            same = False
        else:
            same = (
                got["name"] == want["name"]
                and got["template_id"] == want["template_id"]
                and got["entity_id"] == want["entity_id"]
                and close(got["position"], want["position"])
                and close(got["rotation"], want["rotation"])
                and close(got["scale"], want["scale"])
            )
        ok_all &= same
        if not same:
            print(f"      差异 got={got}\n            want={want}")
    check("逐实体 名称/模板ID/唯一ID/位置/旋转/缩放 全部匹配", ok_all)

    ids = [e["entity_id"] for e in independent]
    check("实体唯一 ID 互不重复", len(set(ids)) == len(ids), str(ids))
    check("实体唯一 ID 连续自 entity_id_start 起",
          ids == list(range(1078000000, 1078000000 + len(ids))), f"{ids[0]}..{ids[-1]}")

    # --- 路径 A：上游真实解析器 ---
    print("\n路径 A — 上游 auto-miliastra 真实解析器")
    upstream, err = decode_payload_upstream(payload, Path(args.upstream_src))
    if upstream is None:
        check("上游解析器可用", False, err)
    else:
        check("上游解析器实体数量一致", len(upstream) == len(independent),
              f"上游 {len(upstream)} vs 独立 {len(independent)}")
        agree = len(upstream) == len(independent) and all(
            u["name"] == i["name"]
            and u["template_id"] == i["template_id"]
            and u["entity_id"] == i["entity_id"]
            and close(u["position"], i["position"])
            and i["scale"] is not None
            and close(u["scale"], i["scale"])
            for u, i in zip(upstream, independent)
        )
        check("上游解析器与本工程解码器结果一致", agree)
        # 上游 miliastra_agent/parsers/entities.py:152-157 用 HasField("scale") 判定，
        # 缺失时填 Vec3(1,1,1)——即上游实现同样会把「缺失」读成 1.0。
        # 这是**第三方静态代码事实**，不是游戏行为结论。本工程不再采用该策略，
        # 故此处显式列出「本地判为缺失」的实体，避免分歧被静默吞掉。
        strict_only = [i["name"] for i in detailed if i["scale_state"] == SCALE_STATE_ABSENT]
        if strict_only:
            print(f"      注意：以下实体本地判为 scale 缺失（上游会回填 1.0）：{strict_only}")
        if upstream:
            s = upstream[0]
            print(f"      上游首实体: name={s['name']} template_id={s['template_id']} "
                  f"entity_id={s['entity_id']} pos={[round(v, 6) for v in s['position']]}")

    print("\n" + "=" * 60)
    if failures:
        print(f"离线校验未通过，{len(failures)} 项失败：")
        for f in failures:
            print("  - " + f)
        return 1
    print(f"离线校验通过（{len(checks)} 项全部 PASS）。")
    print("范围声明：仅证明离线文件可解析且内容自洽，不代表游戏接受该资产或已通关。")
    print("存在性声明：scale 状态按 wire 上的字段存在性判定（absent/present_empty/"
          "present_partial/present_full）；缺失即报缺失，不再静默回填 1.0。")
    print("            「缺失分量读回 0.0」是 proto3 格式默认值，不是业务默认值；"
          "游戏/编辑器如何解释这些状态属未验证项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
