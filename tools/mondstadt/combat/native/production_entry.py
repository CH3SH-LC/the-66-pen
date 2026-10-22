#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""combat 生产链单一入口（**含执行层**，接既有可执行面）。

七段：启用集合 → 创建 → 原生组件 → 行为参数 → 图 → 绑定 → 读回。
**执行层**直接调既有入口（不自建工具）：
  * 创建/保存/实体表：`tools/game-executor/scene_cli.py`  creature-create | inspect | save
  * 构图派发：      `tools/authoring/author.py`            graph build-plan --plan-file <path>
  * 属性/原生组件：   `tools/template-properties/v2/cli.py`
  * .gil 差分：      `tools/beyond-save/field_diff.py <before> <after>`

默认 **dry-run**（只产 argv，不派发）。`--execute` 才真调；raw 异常不重放。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TOOL = "combat-production-entry"
MODULE = "combat-encounters"
CONTRACT_VERSION = 26

CANDIDATE = "data/mondstadt/combat/production-candidate.json"
GROUND_CARDS = "data/mondstadt/outside/terrain/ground-height.cards.json"
GROUND_SHA = "c3999b4973f97b612cfd843d3e44bccbb16a60fd6edbd54997bab1e1bd1512c9"
GROUND_CELLS = 27340
ORDINARY_TEMPLATE = 30002002

#: 既有可执行面（**唯一**允许的调用目标）
ENTRY_SCENE_CLI = "tools/game-executor/scene_cli.py"
#: 既有只读 profile 解码器（`run_delivery.py:40` 同源常量）
ENTRY_READONLY_PROFILE = "tools/game-executor/build_readonly_profile.py"
ENTRY_AUTHOR = "tools/authoring/author.py"
ENTRY_FIELD_DIFF = "tools/beyond-save/field_diff.py"
ENTRY_PROPS = "tools/template-properties/v2/cli.py"

#: HP 读数通道
HP_COMPONENT_KEY = "0x100d000"
HP_PROPERTY_OFFSET = "+138"
HP_PROP = 1010
MAX_HP_PROP = 2000
#: `boundToLevel` 判据里那个**硬编码 level 实体**（`AuthoringGraph.cs:381`）。
#: 只有计划声明为 level-host 的图才把它当作期望绑定目标。
LEVEL_ENTITY_ID = 1094713345


class EntryError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


ERROR_CODES = {
    "INPUT_MISSING", "INPUT_INVALID", "GROUND_SHA_MISMATCH", "GROUND_CELLS_MISMATCH",
    "GROUND_SAMPLER_UNAVAILABLE", "GROUND_SAMPLE_MISSING", "ENABLED_SET_EMPTY",
    "ENABLED_TEMPLATE_NOT_ORDINARY", "TEMPLATE_COMPONENT_MISSING", "NO_ATTACH_VIOLATION",
    "BEHAVIOUR_PARAM_SOURCE_MISSING", "SEMANTIC_IDS_MISSING", "SEMANTIC_KEY_ABSENT",
    "SEMANTIC_ID_NOT_TYPED", "GRAPH_DANGLING", "GRAPH_NOT_DERIVED",
    "BINDING_TARGET_MISSING", "NATIVE_ID_RECEIPT_MISSING", "NATIVE_ID_COUNT_MISMATCH",
    "NATIVE_ID_DUPLICATE", "ENTITY_ID_AMBIGUOUS", "READBACK_ASSERTION_FAILED",
    "DISPATCH_CONTEXT_MISSING", "RAW_EXCEPTION_NOT_REPLAYED",
}


def read_json(rel: str) -> dict:
    p = REPO / rel
    if not p.is_file():
        raise EntryError("INPUT_MISSING", f"{rel} 不存在")
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EntryError("INPUT_INVALID", f"{rel} 第 {exc.lineno} 行：{exc.msg}") from None
    if not isinstance(doc, dict):
        raise EntryError("INPUT_INVALID", f"{rel} 不是 JSON 对象")
    return doc


# ---------------------------------------------------------------- 解析器（缺陷 9/10）
def parse_entity_table(payload: dict) -> dict:
    """**只按编辑实体实例 GUID 建键**；**绝不拿 configId 当 id 兜底**（会合并同模板多怪）。

    ⚠️ **两层身份必须分开**（不得跨层混用）：
      * 编辑实体表里的 `id` = **编辑实例 GUID**（editor instance GUID）；
      * **trial runtimeID** 是运行期映射出来的另一层，**当前无游戏 ⇒ 不伪造映射**。
    """
    rows = payload.get("entities") or payload.get("rows") or []
    by_guid: dict[int, dict] = {}
    missing_id = 0
    for e in rows:
        gid = e.get("id")
        if not isinstance(gid, int) or isinstance(gid, bool):
            gid = e.get("entityId")
        if not isinstance(gid, int) or isinstance(gid, bool):
            missing_id += 1
            continue
        if gid in by_guid:
            raise EntryError("ENTITY_ID_AMBIGUOUS",
                             f"编辑实体 GUID {gid} 在 payload 里重复")
        by_guid[gid] = {"editorInstanceGuid": gid, "owner": e.get("owner"),
                        "config": e.get("config"), "configId": e.get("configId"),
                        "flags": e.get("flags"),
                        # **保留 CaptureComponents 字段级数据**（r22：组件保全要按字段比，
                        # 只比 config 指针会漏判「指针相同但字段被改」）
                        **{k: e[k] for k in
                           ("components", "captureComponents", "CaptureComponents",
                            "componentValues", "componentData")
                           if k in e}}
    return {"count": len(by_guid), "byGuid": by_guid, "rowsWithoutId": missing_id,
            "keyedBy": "editorInstanceGuid(only)",
            "identityLayers": {
                "editorInstanceGuid": "编辑实体表 `id` —— **本函数唯一使用的键**",
                "trialRuntimeId": "**运行期映射的另一层**；无游戏 ⇒ `NOT_RESOLVED`，"
                                  "**不伪造、不从 GUID 推导**",
            },
            "notCrossLayer": True}


def editor_guid_to_runtime_id(guid: int) -> int | None:
    """**两层身份分开**：编辑实体 GUID → trial runtimeID 需要**运行期映射**。

    当前无游戏 ⇒ 一律返回 `None`（**不伪造映射**），调用方必须把它当未解析。
    """
    return None


def extract_native_ids(before: dict, after: dict, expected: int) -> dict:
    """创建后**从实体表差分取新增的编辑实体 GUID**（互不重复）。

    ⚠️ 返回的是 **editor instance GUID**，**不是 trial runtimeID**（两层身份分开）。
    """
    b = parse_entity_table(before)["byGuid"]
    a = parse_entity_table(after)["byGuid"]
    new_ids = sorted(set(a) - set(b))
    if len(new_ids) != expected:
        raise EntryError("NATIVE_ID_COUNT_MISMATCH",
                         f"新增 {len(new_ids)} 个 != 期望 {expected}")
    return {"nativeIds": new_ids, "count": len(new_ids),
            "source": "实体表差分（before→after，按真实 ID）"}


def parse_hp_reads(payload: dict) -> dict:
    """**修缺陷 9**：显式判存在。**合法 HP=0 必须保留**，不得被 `or` 吞成 None。"""
    out: dict[int, dict] = {}
    for k, v in (payload.get("reads") or {}).items():
        row: dict = {}
        for name, prop in (("hp", HP_PROP), ("maxHp", MAX_HP_PROP)):
            found = False
            for key in (str(prop), prop):
                if key in v:                      # **显式 in**，不用 or
                    row[name] = v[key]
                    found = True
                    break
            if not found:
                row[name] = None                  # 只有真缺才 None
        out[int(k)] = row
    return out


def _component_rows(payload_row: dict) -> list[dict] | None:
    """取该实体的 **CaptureComponents 字段级数据**；没有就返回 None。"""
    for key in ("components", "captureComponents", "CaptureComponents",
                "componentValues", "componentData"):
        rows = payload_row.get(key)
        if isinstance(rows, list):
            return [dict(r) for r in rows if isinstance(r, dict)]
    return None


def _canon_components(rows: list[dict]) -> list[dict]:
    """按 `id` 排序的规范化拷贝：**保留全部字段**（不只看 config 指针）。"""
    out = []
    for r in rows:
        cid = r.get("id", r.get("componentId", r.get("kind")))
        fields = {k: v for k, v in r.items()
                  if k not in ("config", "configPointer", "pointer")}
        out.append({"componentId": cid, "fields": fields})
    out.sort(key=lambda c: (str(c["componentId"]), json.dumps(c["fields"],
                                                              sort_keys=True,
                                                              ensure_ascii=False)))
    return out


def _valid_death_evidence(ev) -> bool:
    """**死亡证据必须来自真实字段**（r23 收紧）。

    旧实现 `if eid in de and de[eid]` ⇒ **任意真值都算证据**（含 `"yes"`、`1`、`True`），
    那是空的。现在只认：
      * dict 且 `lifeState == "dead"`（且带证据说明）；
      * 或字符串字面量 `"lifeState=dead"`。
    """
    if isinstance(ev, dict):
        return ev.get("lifeState") == "dead" and bool(ev.get("evidence")
                                                      or ev.get("lifeStateEvidence")
                                                      or ev.get("observedDuringBoundTrial"))
    if isinstance(ev, str):
        return ev.strip() == "lifeState=dead"
    return False


def assert_damage_observed(before_hp: dict, after_hp: dict, *,
                           expected_ids: list[int] | None = None,
                           trial_before: str | None = None,
                           trial_after: str | None = None,
                           death_evidence: dict | None = None,
                           allow_unknown: bool = False) -> dict:
    """**受击/死亡断言（正确口径，r22 重写）**。

    三个此前无效的通道全部堵住：
      1. **实体消失 ≠ 伤害** —— 消失一律进 `unknown`，除非有**明确死亡证据**；
      2. **`before` 空集合不能让断言通过** —— `before` 必须有效且**非空**；
      3. **需同一 trial / 实际宿主** —— `trial_before != trial_after` 直接拒。

    伤害 = 同一 trial + **有效非空前后 HP** + `after.hp < before.hp`。
    死亡 = **明确死亡证据**（`hp == 0` 或 `death_evidence[id]` 给出证据），**不能拿 disappear 顶替**。
    拿不到合法前后值 ⇒ 记 `unknown`，**不得算作已验证**。
    """
    de = death_evidence or {}
    # ---- 通道 2：before 必须有效且非空
    if not isinstance(before_hp, dict) or not before_hp:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "攻击前 HP 集合为空/非法 ⇒ 无法证明伤害（不得以空集通过）")
    if not isinstance(after_hp, dict):
        raise EntryError("READBACK_ASSERTION_FAILED", "攻击后 HP 集合非法（非字典）")
    # ---- 通道 3：同一 trial / 实际宿主
    if trial_before is not None and trial_after is not None \
            and str(trial_before) != str(trial_after):
        raise EntryError("READBACK_ASSERTION_FAILED",
                         f"前后不是同一 trial：{trial_before!r} vs {trial_after!r}")
    if expected_ids is not None and not expected_ids:
        raise EntryError("READBACK_ASSERTION_FAILED", "expected_ids 为空 ⇒ 未指定目标")

    targets = list(expected_ids) if expected_ids is not None else list(before_hp)
    if not targets:
        raise EntryError("READBACK_ASSERTION_FAILED", "无目标实体可核")

    damaged, died, unknown, problems = [], [], [], []
    for eid in targets:
        b = before_hp.get(eid)
        if not isinstance(b, dict) or b.get("hp") is None:
            unknown.append({"id": eid, "why": "攻击前 HP 未读到"})
            continue
        bh = b["hp"]
        if not isinstance(bh, (int, float)) or isinstance(bh, bool):
            unknown.append({"id": eid, "why": f"攻击前 HP 非数值 {bh!r}"})
            continue
        a = after_hp.get(eid)
        # ---- 通道 1：消失**不再**当伤害
        if a is None:
            if _valid_death_evidence(de.get(eid)):
                died.append({"id": eid, "by": f"**真实生命状态证据** {de[eid]!r}"})
            elif eid in de:
                unknown.append({"id": eid,
                                "why": f"死亡证据不合法 {de[eid]!r} ⇒ 只认 "
                                       "`lifeState == 'dead'` 真实字段"})
            else:
                unknown.append({"id": eid,
                                "why": "实体从 after 消失，但**无明确死亡证据** ⇒ "
                                       "消失≠伤害，不计为已验证"})
            continue
        if not isinstance(a, dict) or a.get("hp") is None:
            unknown.append({"id": eid, "why": "攻击后 HP 未读到"})
            continue
        ah = a["hp"]
        if not isinstance(ah, (int, float)) or isinstance(ah, bool):
            unknown.append({"id": eid, "why": f"攻击后 HP 非数值 {ah!r}"})
            continue
        if ah < bh:
            # hp 归零 = 明确死亡证据（显式数值，不是消失推断）
            (died if ah == 0 else damaged).append(
                {"id": eid, "from": bh, "to": ah,
                 "by": "hp 归零（显式数值）" if ah == 0 else "HP 下降"})
        elif ah == bh:
            problems.append(f"id={eid} HP 未变化：{bh} → {ah}（受击未被观察到）")
        else:
            problems.append(f"id={eid} HP 上升：{bh} → {ah}（不是伤害）")

    if problems:
        raise EntryError("READBACK_ASSERTION_FAILED", "; ".join(problems[:5]))
    if unknown and not allow_unknown:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "以下目标**无法判定**，不得算作已验证："
                         + "; ".join(f"{u['id']}({u['why']})" for u in unknown[:5]))
    verified = bool(damaged or died) and not unknown
    return {"verified": verified,
            "damageObserved": bool(damaged),
            "deathObserved": bool(died),
            "damaged": damaged, "died": died, "unknown": unknown,
            "compared": len(targets),
            "disappearanceCountsAsDamage": False,
            "emptyBeforePasses": False,
            "sameTrial": (str(trial_before) == str(trial_after)
                          if trial_before is not None and trial_after is not None
                          else "notChecked")}


def assert_component_delta_zero(before: dict, after: dict, *,
                                protection_fields: tuple[str, ...] =
                                ("editorInstanceGuid", "owner", "configId")) -> dict:
    """**组件快照不得变化（r22 改为字段级比较）**。

    旧实现**只比 `config` 指针** —— 指针相同但组件字段被改时它会漏判。
    现在：有 **CaptureComponents 字段级数据**就逐字段比；**指针相同但字段变必须被拒**。
    指针相同时也报告 `pointerOnly`，让读者知道这一条的证据强度。
    """
    b_tab = parse_entity_table(before)["byGuid"]
    a_tab = parse_entity_table(after)["byGuid"]
    if not b_tab or not a_tab:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "组件保全比较需要**前后都非空**的实体表")

    field_changed, ptr_changed, protection_broken = [], [], []
    pointer_only, field_compared = [], []
    for guid in sorted(set(b_tab) & set(a_tab)):
        eb, ea = b_tab[guid], a_tab[guid]
        # 保护域：身份类字段不得变
        for f in protection_fields:
            if f in eb and f in ea and eb[f] != ea[f]:
                protection_broken.append(f"id={guid} {f}: {eb[f]!r} → {ea[f]!r}")
        cb, ca = _component_rows(eb), _component_rows(ea)
        # **config 指针无论有没有字段数据都要比**（r22：字段一致但指针变了仍是变化）
        pb, pa = eb.get("config"), ea.get("config")
        if pb != pa:
            ptr_changed.append(f"id={guid} config: {pb!r} → {pa!r}")
        if cb is not None and ca is not None:
            kb, ka = _canon_components(cb), _canon_components(ca)
            if kb != ka:
                field_changed.append(f"id={guid} 组件字段变化")
            else:
                field_compared.append(guid)
        else:
            # 没有字段级数据，只能退回指针比较 —— 明确标注证据强度
            if pb == pa:
                pointer_only.append(guid)

    if field_changed or ptr_changed or protection_broken:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "组件/保护域 delta != 0："
                         + "; ".join((field_changed + ptr_changed
                                      + protection_broken)[:5]))
    if not field_compared and not pointer_only:
        raise EntryError("READBACK_ASSERTION_FAILED", "没有任何可比对的实体")
    return {"deltaZero": True,
            "comparedIds": len(set(b_tab) & set(a_tab)),
            "fieldComparedIds": sorted(field_compared),
            "pointerOnlyIds": sorted(pointer_only),
            "evidenceStrength": ("FIELD_LEVEL" if field_compared
                                 else "POINTER_ONLY"),
            "changed": [],
            "protectionDomain": list(protection_fields),
            "pointerOnlyIsNotProof": "**指针相同不证明字段未变**；"
                                     "有 CaptureComponents 时必须按字段比。"}


# ---------------------------------------------------------------- S1
def derive_enabled_set(candidate: dict) -> dict:
    rows = (candidate.get("creationCoordinates") or {}).get("monsters") or []
    if not rows:
        raise EntryError("ENABLED_SET_EMPTY", "候选里没有 monsters")
    eligible: dict[str, list] = {}
    for r in rows:
        if len(r) < 3 or r[2] != ORDINARY_TEMPLATE:
            continue
        eligible.setdefault("camp-" + str(r[0]).split("_")[2].lower(), []).append(r)
    for c in eligible:
        eligible[c].sort(key=lambda r: r[0])
    if not eligible:
        raise EntryError("ENABLED_SET_EMPTY", "没有普通丘丘人候选")
    smallest = min(eligible, key=lambda k: (len(eligible[k]), k))
    picked = list(eligible[smallest][:4])
    for c in sorted(eligible):
        if c != smallest:
            picked.extend(eligible[c][:1])
    picked.sort(key=lambda r: r[0])
    if any(r[2] != ORDINARY_TEMPLATE for r in picked):
        raise EntryError("ENABLED_TEMPLATE_NOT_ORDINARY", "启用集混入非普通丘丘人")
    per_camp: dict[str, int] = {}
    for r in picked:
        c = "camp-" + str(r[0]).split("_")[2].lower()
        per_camp[c] = per_camp.get(c, 0) + 1
    return {"eligibleCount": sum(len(v) for v in eligible.values()),
            "smallestCamp": smallest, "enabledRefs": [r[0] for r in picked],
            "enabledCount": len(picked), "perCamp": per_camp,
            "reserveCount": len(rows) - len(picked), "rows": picked, "derived": True}


# ---------------------------------------------------------------- ground
def load_ground(ground_path: str | None) -> dict:
    rel = ground_path or GROUND_CARDS
    p = REPO / rel if not Path(rel).is_absolute() else Path(rel)
    if not p.is_file():
        raise EntryError("INPUT_MISSING", f"ground cards {rel} 不存在")
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != GROUND_SHA:
        raise EntryError("GROUND_SHA_MISMATCH", f"实际 {actual} != 当前 {GROUND_SHA}")
    sys.path.insert(0, str(REPO / "tools/mondstadt/integration"))
    try:
        import ground_sampler as gs
    except Exception as exc:  # noqa: BLE001
        raise EntryError("GROUND_SAMPLER_UNAVAILABLE", str(exc)) from None
    sampler = gs.GroundSampler(p)
    if sampler.cell_count != GROUND_CELLS:
        raise EntryError("GROUND_CELLS_MISMATCH", f"{sampler.cell_count} != {GROUND_CELLS}")
    return {"path": rel, "sha256": actual, "cells": sampler.cell_count,
            "sampler": sampler, "samples": {}}


# ---------------------------------------------------------------- S2
def plan_creation(enabled: dict, ground: dict, ctx: dict) -> dict:
    """**修缺陷 3**：argv 带齐 session / level / review / queue（scene_cli 必需）。"""
    missing = [k for k in ("session", "levelId", "queue") if not ctx.get(k)]
    if missing:
        raise EntryError("DISPATCH_CONTEXT_MISSING",
                         f"缺 {missing}；scene_cli 写入必须带 "
                         "--session/--level-id/--review/--elevated-queue"
                         "（review 按实体逐个给，见 reviews{}）")
    reviews = require_fresh_reviews(ctx, [r[0] for r in enabled["rows"]])
    steps = []
    for r in enabled["rows"]:
        ref, template, pos, rot = r[0], r[2], r[3], r[4]
        s = ground["samples"].get(ref)
        if not s:
            raise EntryError("GROUND_SAMPLE_MISSING", f"{ref} 无地面采样")
        y = s["groundY"]
        steps.append({
            "ref": ref, "templateId": template,
            "position": [pos[0], y, pos[2]], "rotation": rot, "scale": [1.0, 1.0, 1.0],
            "positionSourceY": s.get("source") or f"ground[{s['cell']}]=code{s['code']}",
            "review": str(reviews[ref]),
            "argv": [sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI), "creature-create",
                     "--template-id", str(template),
                     "--position", f"{pos[0]}", f"{y}", f"{pos[2]}",
                     "--rotation", *[str(v) for v in rot],
                     "--scale", "1", "1", "1",
                     "--session", str(ctx["session"]),
                     "--level-id", str(ctx["levelId"]),
                     "--review", str(reviews[ref]),
                     "--elevated-queue", str(ctx["queue"])],
            "verifyBy": "实体表差分（不看 placedCount）",
        })
    return {"count": len(steps), "steps": steps, "path": "scene_cli creature-create"}


# ---------------------------------------------------------------- S3
def assert_template_native(candidate: dict) -> dict:
    """**修缺陷 12**：缺模板组件必须**真拒**（不再只算 missing 就放过）。"""
    mount = candidate.get("mountAndConfigure") or {}
    inherited = (candidate.get("behaviourConsumption") or {}).get("behaviours") or []
    carriers: list[int] = []
    for b in inherited:
        carriers.extend(b.get("carrierKinds") or ([b["carrierKind"]] if b.get("carrierKind") else []))
    if mount.get("attachRequiredForCombat") or any(
            k.get("attachRequired") for k in (mount.get("perKind") or [])):
        raise EntryError("NO_ATTACH_VIOLATION", "候选声明需要 attach 组件")
    need = {26, 4, 9, 12, 18, 11, 20, 19}
    missing = sorted(need - set(carriers))
    if missing:                                   # **真拒**
        raise EntryError("TEMPLATE_COMPONENT_MISSING",
                         f"模板不再自带 {missing} ⇒ 战斗行为不成立，需重新评估")
    return {"attachRequiredForCombat": False, "attachedKinds": [],
            "templateCarrierKinds": sorted(set(carriers)),
            "requiredKinds": sorted(need), "missingFromTemplate": [],
            "verdict": "TEMPLATE_NATIVE_NO_ATTACH"}


# ---------------------------------------------------------------- S4
#: **必须拒绝的合成/历史 fixture 货币值**。它们曾经进过本模块的产物，
#: 一旦被当成生产 currency 部署，就会与 life 侧货币不成同一池。
SYNTHETIC_CURRENCY_FIXTURES = {
    993001: "合成 fixture（本模块 r19–r21 回归里用过）",
    1115684865: "1842 旧口径遗留值（legacyValueSeenInThisModule）",
    4350: "旧测试常量（entry1x build-plan 里出现过，来源未证）",
}

#: 727 端口的**权威类型**。消费者按此转换，而不是要求上游回执自带 slot/type。
PORT727_CURRENCY_SLOT = "uint"
_UINT32_MAX = 0xFFFFFFFF


def resolve_currency_from_semantic_receipt(
        receipt: dict | None, *,
        operation: dict | None = None,
        session_file: str | None = None,
        session_sha256: str | None = None,
        require_session_proof: bool = False,
        target_level_id: int | None = None,
        semantic_key: str = "currency.mora",
        receipt_path: str | None = None,
        receipt_sha256: str | None = None) -> dict:
    """**消费 `definition_sequence.register` 的真实回执**，解析出 727 port1 的 currency 值。

    真实契约（`tools/editor-bridge/native-card/definition_sequence.py`：`:171` 签名、
    `:288-292` 成功回执、`:212-215` operation.json、`:280-284` 逐条 record）：
      - `register(document, *, operation_id, session_file, target_gil, backup,
        queue, reviewed_source_sets, fresh_baseline, _commands=None)`；
      - 成功回执**没有顶层 `session` / `targetLevelId`**，只有 **`levelId`**；
      - 回执含 `ok=True`、`state='catalog-registered-only'`、`semanticIds`（**role:int**）、
        `registeredDefinitions`、`outcomeUncertain=False`；
      - 逐条 record 带 **`catalogRegisteredVerified=True`** 与 `configId`；
      - `operation.json` 的 `inputs` 是 **{文件绝对路径: sha256}**（session/recovery/target）。

    因此本函数**不要求上游不存在的字段**：
      * session 身份 ⇒ 用 `operation.json.inputs` 里对应 session 文件的 sha256
        与本次实际 session 指纹比对（**不找回执顶层 session**）；
      * 关卡 ⇒ 用回执的 **`levelId`**（**不是** `targetLevelId`）。

    **仅"拒绝 fixture"不构成真实性证据**；真实性由
    `ok / state / outcomeUncertain / levelId / session 指纹 / catalogRegisteredVerified`
    这组证据共同支撑，fixture 黑名单只作额外兜底。
    """
    if not isinstance(receipt, dict) or not receipt:
        raise EntryError("SEMANTIC_RECEIPT_MISSING",
                         "缺 `definition_sequence.register` 回执；"
                         "不能用固定整数或 fixture 顶替 currency")

    # ---- 1) 回执形态：ok / state / outcomeUncertain 三项精确匹配 ----
    if receipt.get("ok") is not True:
        raise EntryError("SEMANTIC_RECEIPT_NOT_OK",
                         f"回执 ok={receipt.get('ok')!r}（要求 True）；"
                         f"state={receipt.get('state')!r}")
    if receipt.get("state") != "catalog-registered-only":
        raise EntryError("SEMANTIC_RECEIPT_STATE",
                         f"回执 state={receipt.get('state')!r}，"
                         "要求 'catalog-registered-only'")
    if receipt.get("outcomeUncertain") is not False:
        raise EntryError("SEMANTIC_RECEIPT_UNCERTAIN",
                         f"回执 outcomeUncertain={receipt.get('outcomeUncertain')!r}"
                         "（要求精确 False；不确定的结果不得消费）")

    # ---- 2) 关卡：真实字段是 levelId（回执无 targetLevelId）----
    rec_level = receipt.get("levelId")
    if target_level_id is not None:
        if rec_level is None:
            raise EntryError("SEMANTIC_RECEIPT_IDENTITY_MISSING",
                             "调用方给了 target level，但回执未携带 levelId ⇒ 无法验证")
        if int(rec_level) != int(target_level_id):
            raise EntryError(
                "SEMANTIC_RECEIPT_IDENTITY_MISMATCH",
                f"回执 levelId={rec_level!r} 与本次 level={target_level_id!r} 不符")

    # ---- 2b) operation.json 与回执必须**同源**（operationId / plan.levelId）----
    if isinstance(operation, dict):
        _op_id = operation.get("operationId")
        if _op_id is not None and receipt.get("operationId") is not None \
                and str(_op_id) != str(receipt.get("operationId")):
            raise EntryError(
                "SEMANTIC_OPERATION_ID_MISMATCH",
                f"operation.json.operationId={_op_id!r} 与回执 operationId="
                f"{receipt.get('operationId')!r} **不同源** ⇒ 不是同一次 register")
        _plan = operation.get("plan") if isinstance(operation.get("plan"), dict) else {}
        _plan_level = _plan.get("levelId") if isinstance(_plan, dict) else None
        if _plan_level is None:
            _plan_level = operation.get("levelId")
        if _plan_level is not None and rec_level is not None \
                and int(_plan_level) != int(rec_level):
            raise EntryError(
                "SEMANTIC_PLAN_LEVEL_MISMATCH",
                f"operation.plan.levelId={_plan_level!r} 与回执 levelId={rec_level!r} "
                "**不同源** ⇒ 回执与 operation 目录不配套")

    # ---- 3) session 身份：走 operation.json 的 inputs 指纹（不要求回执带 session）----
    session_proof: dict = {"verified": False, "reason": "未提供 session 文件"}
    if session_file is None:
        # **execute 路径必须核 session 身份**：缺文件即拒，不能默默跳过校验。
        if require_session_proof:
            raise EntryError(
                "SEMANTIC_SESSION_PROOF_REQUIRED",
                "execute 路径要求核 session 身份，但未提供可读的 session 文件 "
                "⇒ 不得继续（prepare 路径也应标未验证，而非 verified=True）")
    else:
        if not isinstance(operation, dict) or not operation.get("inputs"):
            raise EntryError(
                "SEMANTIC_OPERATION_EVIDENCE_MISSING",
                "核 session 身份需要 operation.json 的 inputs（路径→sha256）；"
                "真实回执不含顶层 session，故不能用回执字段替代")
        inputs = operation["inputs"]
        # **按解析后的绝对路径精确匹配**：只比 `Path.name` 会把两个不同目录下
        # 同名的 session 文件误认成同一次 register。
        try:
            want = str(Path(str(session_file)).resolve()).lower()
        except (OSError, ValueError):
            raise EntryError("SEMANTIC_SESSION_PATH_UNRESOLVABLE",
                             f"session 文件路径无法解析：{session_file!r}")
        match = None
        for k, v in inputs.items():
            try:
                k_res = str(Path(str(k)).resolve()).lower()
            except (OSError, ValueError):
                k_res = str(k).lower()
            if k_res == want:
                match = (k, v)
                break
        if match is None:
            raise EntryError(
                "SEMANTIC_SESSION_NOT_IN_OPERATION_INPUTS",
                f"operation.json.inputs 中没有**解析后绝对路径**等于 {want!r} 的项"
                f"（只比文件名会误认同名 session）；实际 keys={list(inputs)[:6]}")
        rec_sha = match[1]
        # **sha 必须真算出来**：为 None 时写 verified=True 等于假验证。
        if not session_sha256:
            raise EntryError(
                "SEMANTIC_SESSION_FINGERPRINT_UNVERIFIED",
                "当前 session 文件没有可用的 sha256 ⇒ **不得**写 verified=True"
                "（文件不存在/不可读/未计算）")
        if str(session_sha256) != str(rec_sha):
            raise EntryError(
                "SEMANTIC_SESSION_FINGERPRINT_MISMATCH",
                f"session 实际 sha256={session_sha256} 与 operation.json 记录 {rec_sha} 不符 "
                "⇒ 不是同一次 register 用的 session")
        session_proof = {"verified": True,
                         "matchBy": "resolved-absolute-path",
                         "operationInputKey": match[0],
                         "recordedSha256": rec_sha,
                         "computedSha256": session_sha256}

    # ---- 2) 取 role:int（容器写法容错，但**值必须是裸 int**）----
    holder = receipt
    for key in ("ids", "semanticIds"):
        if isinstance(holder.get(key), dict):
            holder = holder[key]
            break
    raw = holder.get(semantic_key)
    if raw is None:
        raise EntryError("SEMANTIC_KEY_ABSENT",
                         f"回执里没有 `{semantic_key}`（回执顶层键={list(receipt)[:8]}）")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EntryError(
            "SEMANTIC_ID_NOT_INT",
            f"`{semantic_key}` 应为 role:int（definition_sequence 的返回形态），"
            f"实得 {type(raw).__name__}={raw!r}")

    # ---- 4) registeredDefinitions 证据：该 role 的 ID 必须 catalogRegisteredVerified ----
    # 真实 record（definition_sequence.py:280-284）带 catalogRegisteredVerified=True /
    # configId / requestSha256 / sourceRun / cardRun / nativeAcceptance / rawSha256。
    # 这是**真实性证据**；仅"不在 fixture 黑名单"不构成真实性。
    defs = receipt.get("registeredDefinitions")
    if not isinstance(defs, list) or not defs:
        raise EntryError("SEMANTIC_DEFINITIONS_MISSING",
                         "回执没有 registeredDefinitions ⇒ 无法证明该 role 已注册进 catalog")
    entry = next((d for d in defs if isinstance(d, dict)
                  and (d.get("key") == semantic_key
                       or d.get("semanticKey") == semantic_key)), None)
    if entry is None:
        raise EntryError(
            "SEMANTIC_DEFINITION_NOT_REGISTERED",
            f"registeredDefinitions 里没有 `{semantic_key}`；"
            f"实际 keys={[d.get('key') for d in defs if isinstance(d, dict)][:8]}")
    if entry.get("catalogRegisteredVerified") is not True:
        raise EntryError(
            "SEMANTIC_DEFINITION_NOT_VERIFIED",
            f"`{semantic_key}` 的 catalogRegisteredVerified="
            f"{entry.get('catalogRegisteredVerified')!r}（要求精确 True）")
    # **configId 必须存在且是精确 int，并等于 semanticIds 值**：
    # 旧写法 `if cfg is not None and ...` 会在 configId 缺失时**绕过**校验。
    cfg = entry.get("configId")
    if isinstance(cfg, bool) or not isinstance(cfg, int):
        raise EntryError(
            "SEMANTIC_DEFINITION_CONFIGID_MISSING",
            f"`{semantic_key}` 的 registeredDefinitions.configId={cfg!r} "
            "必须是精确 int（缺失/非 int 都不得绕过一致性校验）")
    if int(cfg) != int(raw):
        raise EntryError(
            "SEMANTIC_DEFINITION_ID_MISMATCH",
            f"semanticIds 里 `{semantic_key}`={raw} 与 registeredDefinitions.configId="
            f"{cfg!r} 不一致 ⇒ 不是同一次注册产物")

    # ---- 5) 合成 fixture 黑名单（**额外兜底**，不是真实性依据）----
    if raw in SYNTHETIC_CURRENCY_FIXTURES:
        raise EntryError(
            "SEMANTIC_ID_IS_SYNTHETIC_FIXTURE",
            f"`{semantic_key}`={raw} 是 {SYNTHETIC_CURRENCY_FIXTURES[raw]} ⇒ **拒绝**，"
            "必须使用 definition_sequence.register 产出的真实 ID")

    # ---- 6) 按 727 端口权威类型转换（我方边界内）----
    if not (0 <= raw <= _UINT32_MAX):
        raise EntryError(
            "SEMANTIC_ID_OUT_OF_UINT32",
            f"`{semantic_key}`={raw} 超出 727 端口 {PORT727_CURRENCY_SLOT} 的值域 "
            f"(0..{_UINT32_MAX})")

    return {
        "currencyId": int(raw),
        "slot": PORT727_CURRENCY_SLOT,
        "slotTypeAuthority": "port727",
        "conversionRule": "role:int → 727 port1 uint（消费者边界内转换；"
                          "不要求上游回执自带 slot/type）",
        "authenticityEvidence": {
            "ok": True,
            "state": "catalog-registered-only",
            "outcomeUncertain": False,
            "levelId": rec_level,
            "sessionProof": session_proof,
            "catalogRegisteredVerified": True,
            "configId": int(raw),
            "requestSha256": entry.get("requestSha256"),
            "sourceRun": entry.get("sourceRun"),
            "cardRun": entry.get("cardRun"),
            "rawSha256": entry.get("rawSha256"),
        },
        "provenance": {
            "semanticKey": semantic_key,
            "rawRoleInt": int(raw),
            "receiptPath": receipt_path,
            "receiptSha256": receipt_sha256,
            "levelId": rec_level,
            "session": session_proof,
            "operationId": receipt.get("operationId"),
            "operationRun": receipt.get("run"),
            "source": "definition_sequence.register "
                      "(tools/editor-bridge/native-card/definition_sequence.py:288-292)",
            "notSynthetic": True,
            "authenticityNotFromFixtureBlacklist": True,
        },
    }


def resolve_behaviour_params(candidate: dict, semantic_ids: dict | None,
                             *, receipt_path: str | None = None,
                             receipt_sha256: str | None = None,
                             operation: dict | None = None,
                             session_file: str | None = None,
                             session_sha256: str | None = None,
                             require_session_proof: bool = False,
                             target_level_id: int | None = None) -> dict:
    """四类来源；**currency 必须 typed 且来自 semanticIds**。"""
    params = []
    for b in (candidate.get("behaviourConsumption") or {}).get("behaviours") or []:
        how = b.get("consumedHow")
        if how == "INHERITED":
            params.append({"behaviour": b.get("behaviour"), "source": "TEMPLATE_NATIVE",
                           "writes": False,
                           "carrier": b.get("carrierKind") or b.get("carrierKinds")})
        elif how == "NODE_GRAPH":
            params.append({"behaviour": b.get("behaviour"), "source": "GRAPH_VALUE",
                           "writes": True, "writtenBy": "S5"})
    cur_id, cur_typed, cur_prov = None, None, None
    if semantic_ids:
        # **按 lead 纠正**：`definition_sequence` 返回的 semanticIds 是 `role:int`，
        # **不要求**上游回执自带 slot/type；类型转换由本消费者按 727 端口权威类型
        # （uint）完成，并保留来源。旧写法对裸 int 抛 SEMANTIC_ID_NOT_TYPED 是错的。
        resolved = resolve_currency_from_semantic_receipt(
            semantic_ids if isinstance(semantic_ids, dict) else None,
            operation=operation, session_file=session_file,
            session_sha256=session_sha256,
            require_session_proof=require_session_proof,
            target_level_id=target_level_id,
            receipt_path=receipt_path, receipt_sha256=receipt_sha256)
        cur_id = resolved["currencyId"]
        cur_typed = {"slot": resolved["slot"], "type": "currency",
                     "semanticKey": "currency.mora",
                     "slotTypeAuthority": resolved["slotTypeAuthority"],
                     "conversionRule": resolved["conversionRule"]}
        cur_prov = resolved["provenance"]
    params.append({"behaviour": "货币奖励 (currency)", "source": "SEMANTIC_ID",
                   "semanticKey": "currency.mora", "resolvedValue": cur_id,
                   "typed": cur_typed, "provenance": cur_prov,
                   "writes": True, "writtenBy": "S5 727 port1"})
    params.append({"behaviour": "巡逻路点", "source": "DATA_RECORD",
                   "from": "camp-instances.json patrolRoutes", "writes": False})
    for row in params:
        if not row.get("source"):
            raise EntryError("BEHAVIOUR_PARAM_SOURCE_MISSING", str(row))
    return {"params": params, "semanticIdResolved": cur_id is not None,
            "currencyId": cur_id, "currencyTyped": cur_typed,
            "currencyProvenance": cur_prov,
            # **真实性状态**：session 指纹已核 + catalogRegisteredVerified=True 才算
            # authenticityVerified。prepare 路径若未核 session，这里必须是 False。
            "authenticityVerified": bool(
                cur_prov and (cur_prov.get("session") or {}).get("verified") is True),
            "noFieldNameRegex": True}


# ---------------------------------------------------------------- S5
DROP_RANGE = {"camp-a": [20, 35], "camp-b": [60, 90], "camp-c": [30, 45]}


def derive_drop_count(camp: str, enabled_n: int) -> int:
    lo, hi = DROP_RANGE.get(camp, [20, 35])
    span = hi - lo
    return max(lo, min(hi, lo + (span * min(enabled_n, 4)) // 8))


def build_graph_plan(candidate: dict, enabled: dict, currency_id: int | None,
                     plan_dir: Path) -> dict:
    """**修缺陷 1/2/4**：currency 真灌进 727 port1；port2 派生；产 schema 正确的 plan 文件。"""
    graphs = candidate.get("completeGraphs") or {}
    if not graphs:
        raise EntryError("GRAPH_NOT_DERIVED", "候选里没有 completeGraphs")
    if currency_id is None:
        raise EntryError("SEMANTIC_IDS_MISSING",
                         "727 port1 需要真实 currency ID；不得沿用候选里的旧 farming 值")
    per_camp: dict[str, int] = {}
    for ref in enabled["enabledRefs"]:
        c = "camp-" + ref.split("_")[2].lower()
        per_camp[c] = per_camp.get(c, 0) + 1

    instances, plan_files = [], []
    for camp in sorted(per_camp):
        g = graphs.get(camp)
        if not g:
            raise EntryError("GRAPH_NOT_DERIVED", f"{camp} 没有图定义")
        n = per_camp[camp]
        nodes = [{"definitionId": d, "x": x, "y": y}
                 for (_a, d, x, y) in (g.get("nodes") or [])]
        alias_idx = {a: i for i, (a, _d, _x, _y) in enumerate(g.get("nodes") or [])}
        edges = [{"from": alias_idx[f], "to": alias_idx[t],
                  "fromKind": fk, "fromIndex": fi, "toKind": tk, "toIndex": ti}
                 for (f, t, fk, fi, tk, ti) in (g.get("edges") or [])]
        values = []
        for v in g.get("values") or []:
            node, port, slot, val = v[0], v[1], v[2], v[3]
            if node == "add_drop_currency":
                if port == 1:
                    val, slot = int(currency_id), "uint"     # **真值灌入 port1**
                elif port == 2:
                    val = derive_drop_count(camp, n)
            elif node.startswith("mark_") and slot == "string":
                val = f"{val} [enabled={n}]"
            values.append({"node": alias_idx[node], "portIndex": port,
                           "slot": slot, "value": val})
        # **真实 plan 格式**：nodes 无 alias；edges 的 from/to 与 values 的 node
        # 都是 **nodes 的零基索引**（author.py:735-739 自述）。
        plan_doc = {"nodes": nodes, "edges": edges, "values": values}
        plan_dir.mkdir(parents=True, exist_ok=True)
        pf = plan_dir / f"{camp}.build-plan.json"
        pf.write_text(json.dumps(plan_doc, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
        plan_files.append(str(pf))
        instances.append({"campRef": camp, "graphNativeName": g.get("name"),
                          "graphRef": g.get("ref"), "graphKind": g.get("graphKind", 20000),
                          "enabledEntities": n, "values": values,
                          "nodeCount": len(plan_doc["nodes"]),
                          "edgeCount": len(plan_doc["edges"]),
                          # 供 S7 按**真实节点索引**核对 port1（缺陷 6）
                          "_planNodes": plan_doc["nodes"],
                          "planFile": str(pf),
                          "argv": [sys.executable, "-B", str(REPO / ENTRY_AUTHOR),
                                   "graph", "build-plan", "--plan-file", str(pf)],
                          "graphIdSource": "graph lookup → backend.graphId（注入后续每一步）"})
    dangling = _dangling(instances, graphs)
    if dangling:
        raise EntryError("GRAPH_DANGLING", "; ".join(dangling[:3]))
    return {"instanceCount": len(instances), "instances": instances,
            "planFiles": plan_files, "currencyAppliedTo727Port1": int(currency_id),
            "instancesDerivedFromEnabledSet": True, "danglingProblems": []}


def _dangling(instances: list[dict], graphs: dict) -> list[str]:
    roots = {374, 375, 380, 620, 304, 373}
    out = []
    for inst in instances:
        g = graphs[inst["campRef"]]
        alias = {n[0]: n[1] for n in (g.get("nodes") or [])}
        incoming = {e[1] for e in (g.get("edges") or [])}
        for a, did in alias.items():
            if did not in roots and a not in incoming:
                out.append(f"{inst['campRef']}: {a}(id={did}) 无入边")
    return out


# ---------------------------------------------------------------- S6
def bind_entities_to_graph(enabled: dict, graph_plan: dict,
                           native_ids: dict | None) -> dict:
    """**逐实体**绑定：`native_ids` 必须是 **ref→entityId 的字典**（来自各自 create 回执）。

    **不 zip 排序后的 ID 列表** —— 那是「看着像」的猜法。
    """
    if not native_ids:
        raise EntryError("NATIVE_ID_RECEIPT_MISSING",
                         "缺逐实体 create 回执 ⇒ 拿不到精确 entityId（不得用 None 占位）")
    if not isinstance(native_ids, dict):
        raise EntryError("NATIVE_ID_RECEIPT_MISSING",
                         "native_ids 必须是 ref→entityId 字典（**不接受排序列表 zip**）")
    missing = [r[0] for r in enabled["rows"] if r[0] not in native_ids]
    if missing:
        raise EntryError("NATIVE_ID_RECEIPT_MISSING", f"缺这些 ref 的回执 ID：{missing}")
    by_camp = {i["campRef"]: i for i in graph_plan["instances"]}
    bindings = []
    for r in enabled["rows"]:
        ref = r[0]
        nid = native_ids[ref]
        camp = "camp-" + ref.split("_")[2].lower()
        inst = by_camp.get(camp)
        if not inst:
            raise EntryError("BINDING_TARGET_MISSING", f"{ref} 所属 {camp} 无图实例")
        bindings.append({"entityRef": ref, "nativeId": int(nid), "campRef": camp,
                         "graphRef": inst["graphRef"],
                         "graphNativeName": inst["graphNativeName"],
                         "nativeIdSource": "**该 ref 自己的 create 回执**（非差分排序）"})
    return {"bindingCount": len(bindings), "bindings": bindings,
            "derivedFromEnabledSet": True, "perEntityReceipt": True}


# ---------------------------------------------------------------- S7
def graph_backend(rec: dict, where: str) -> dict:
    """**取 author.py 外层 JSON 里的 `backend`**（真实动作回执在这一层）。

    `author.py:604` 的外层结构 = `{ok, requestId, backend:{…}, retryAttempted,
    replayed, journal, persistenceVerified:false, officialPlaytestVerified:false}`
    ⇒ `graphId` / `boundEntityIds` / `boundToLevel` **都在 `backend` 里**，不在顶层。
    """
    doc = rec.get("parsed") or {}
    be = doc.get("backend")
    if not isinstance(be, dict):
        raise EntryError("GRAPH_NOT_DERIVED",
                         f"{where}: author.py 外层无 backend（journal={rec.get('journal')}）")
    if be.get("ok") is not True:
        raise EntryError("GRAPH_NOT_DERIVED",
                         f"{where}: backend.ok != True（status={be.get('status')}）")
    return be


def parse_graph_state(be: dict) -> dict:
    """**解析 inspect/lookup 的一等字段**（`AuthoringGraph.cs:382-386`）。"""
    return {
        "status": be.get("status"),
        "name": be.get("name"),
        "graphId": be.get("graphId"),
        "nodeCount": be.get("nodeCount"),
        # 384-385：绑定目标图为该图的实体，取**真实实体 ID** 去重
        "boundEntityIds": [int(x) for x in (be.get("boundEntityIds") or [])],
        "boundToLevel": bool(be.get("boundToLevel")),
        "nodes": [{"nodeId": n.get("nodeId"), "definitionId": n.get("definitionId")}
                  for n in (be.get("nodes") or []) if isinstance(n, dict)],
        "runtimeVerified": be.get("runtimeVerified"),
        "persistentSaveVerified": be.get("persistentSaveVerified"),
    }


def extract_graph_id(be: dict, where: str) -> str:
    """**从 lookup/inspect 的 backend 取真实 graphId**。

    `AuthoringGraph.cs:363`：`lookup` 无匹配时返回 `{status:"lookup-pending"}`
    —— **没有 graphId**，那是「还没建好」，不是「ID 为空」。
    """
    gid = be.get("graphId")
    if isinstance(gid, int) and not isinstance(gid, bool):
        return str(gid)
    if isinstance(gid, str) and gid.isdigit():
        return gid
    raise EntryError("GRAPH_NOT_DERIVED",
                     f"{where}: 未给出 graphId（status={be.get('status')}）；"
                     "**不猜、不预设**，也不把 lookup-pending 当 ID")


def assert_bind_requested(be: dict, where: str) -> dict:
    """**bind 回执只代表「已请求、待读回」**（`AuthoringGraph.cs:451`）。

    ⇒ **绝不能当绑定成功**；必须再 inspect 用 `boundEntityIds` 确认。
    """
    status = be.get("status")
    if status != "binding-requested-readback-pending":
        raise EntryError("READBACK_ASSERTION_FAILED",
                         f"{where}: bind 回执 status={status!r}，"
                         "期望 'binding-requested-readback-pending'")
    if be.get("persistentSaveVerified") or be.get("runtimeVerified"):
        raise EntryError("READBACK_ASSERTION_FAILED",
                         f"{where}: bind 回执声称 persistentSaveVerified/runtimeVerified —— "
                         "该入口按设计**两者恒为 false**，回执不可信")
    return {"status": status, "graphId": be.get("graphId"),
            "entityId": be.get("entityId"), "treatAsSuccess": False,
            "mustConfirmBy": "graph inspect → boundEntityIds"}


def assert_bound_confirmed(state: dict, expected_ids: list[int], where: str, *,
                           graph_id: str | None = None,
                           host_kind: str = "monster-host",
                           expected_node_defs: list[int] | None = None) -> dict:
    """**绑定成功判据（按 `AuthoringGraph.cs:380-385` 的真实契约）**。

    成功 = ① `set(计划目标 editor 实体 GUID) ⊆ set(boundEntityIds)`
          ② `graphId` 与 inspect 回执**一致**
          ③ 节点原件（definitionId 集合）与计划一致

    **`boundToLevel` 不是绑定成功标志**：`State` 先筛出实体 ID == `1094713345` 的
    level 实体，再判断**它**是否绑了本图 ⇒ 绑丘丘人的图**应当为 false**。
    只有**计划声明为 level-host** 的图才要求 `true` 且 level 实体 ID 1094713345。

    ⇒ **绝不拿 `boundToLevel == true` 当成功判据**（会把合法怪物图拒掉，
    还会诱导把实体图错绑到全局 level —— 本会话反复禁止的「改语义凑检查」）。
    """
    got = set(state.get("boundEntityIds") or [])
    missing = sorted(set(expected_ids) - got)
    if missing:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         f"{where}: inspect.boundEntityIds 缺 {missing}；实得 {sorted(got)}")

    if graph_id is not None:
        seen = state.get("graphId")
        if seen is None or str(seen) != str(graph_id):
            raise EntryError("READBACK_ASSERTION_FAILED",
                             f"{where}: 回执 graphId={seen!r} != 请求 {graph_id}")

    if expected_node_defs:
        got_defs = sorted(n.get("definitionId") for n in (state.get("nodes") or []))
        if got_defs != sorted(expected_node_defs):
            raise EntryError("READBACK_ASSERTION_FAILED",
                             f"{where}: 节点原件不符；回执={got_defs} "
                             f"计划={sorted(expected_node_defs)}")

    if host_kind == "level-host":
        if state.get("boundToLevel") is not True:
            raise EntryError("READBACK_ASSERTION_FAILED",
                             f"{where}: 本图为 level-host，要求 boundToLevel==true 且绑到 "
                             f"level 实体 {LEVEL_ENTITY_ID}，实得 false")
        level_check = {"required": True, "ok": True, "levelEntityId": LEVEL_ENTITY_ID}
    else:
        level_check = {"required": False, "status": "notRequiredOrMayBeFalse",
                       "observed": state.get("boundToLevel"),
                       "why": "怪物宿主图 `boundToLevel` 为 false 是**正常且期望**的；"
                              "**不因它 false 而拒**"}
    return {"confirmed": True, "boundEntityIds": sorted(got),
            "expected": sorted(set(expected_ids)),
            "graphId": state.get("graphId"), "graphIdConsistent": True,
            "nodeOriginals": "matched" if expected_node_defs else "notChecked",
            "hostKind": host_kind, "boundToLevel": level_check,
            "consumedFields": ["boundEntityIds", "graphId", "nodes", "boundToLevel"]}


def replace_graph_id(argv: list[str], graph_id: str) -> list[str]:
    """把 argv 里的 `<from-lookup>` 占位**替换成真实 graphId**。"""
    out = list(argv)
    for i, a in enumerate(out):
        if a == "--graph-id" and i + 1 < len(out):
            out[i + 1] = str(graph_id)
            return out
    raise EntryError("GRAPH_NOT_DERIVED", "argv 缺 --graph-id")


def graph_node_defs(candidate: dict, camp: str) -> list[int]:
    """该营地计划图的 definitionId 序列（用于**节点原件**核对）。"""
    g = (candidate.get("completeGraphs") or {}).get(camp) or {}
    return [int(d) for (_a, d, _x, _y) in (g.get("nodes") or [])]


def unique_graph_name(ctx: dict, camp: str) -> str:
    """**唯一名称**：`AuthoringGraph.cs:364` 要求 `matches.Length==1`，
    同名图只允许一张 ⇒ 名称带 camp + runId 以区分三张图。"""
    base = ctx.get("graphNamePrefix") or "MW_API_COMBAT"
    return f"{base}_{camp}_{ctx['runId']}"


def currency_port1_by_real_node(inst: dict) -> list:
    """**缺陷 6 修**：按 `add_drop_currency` 的**真实节点索引**核对 port1。

    旧写法 `... or True` 会混入所有 uint port1 ⇒ 这里先解析每个 value 的
    `node` 索引，再在**该索引对应的节点**上判定 definitionId 是否为 727。
    """
    plan_nodes = inst.get("_planNodes") or []
    out = []
    for v in inst.get("values") or []:
        idx = v.get("node")
        port = v.get("portIndex")
        slot = v.get("slot")
        if not isinstance(idx, int) or port != 1 or slot != "uint":
            continue
        if not (0 <= idx < len(plan_nodes)):
            raise EntryError("GRAPH_NOT_DERIVED",
                             f"{inst['campRef']}: value.node={idx} 超出 nodes 范围")
        defid = plan_nodes[idx].get("definitionId")
        if defid != 727:
            continue                                  # **只认真正的 727 节点**
        out.append({"nodeIndex": idx, "definitionId": defid, "value": v.get("value")})
    return out


def build_readback_plan(enabled: dict, graph_plan: dict) -> dict:
    """**修缺陷 6/11**：真实命令 + **独立目标字段** + **保护域**断言。"""
    ops = [
        {"id": "OBS-ENTITY-TABLE-BEFORE", "when": "创建前",
         "argv": [sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI), "inspect"]},
        {"id": "OBS-ENTITY-TABLE-AFTER", "when": "创建后",
         "argv": [sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI), "inspect"],
         "assert": f"新增实体数 == {enabled['enabledCount']}；**按真实运行 ID 匹配，不按 configId**"},
        {"id": "OBS-GRAPH-TARGET-FIELDS", "when": "build-plan 之后",
         "reads": ["graph.name", "graph.graphKind",
                   "values[node=add_drop_currency,portIndex=1]"],
         "assert": "**独立目标字段**：图名/kind/727 port1 必须等于计划值（不是只看『差分非空』）"},
        {"id": "OBS-COMPONENTS-DELTA", "when": "创建后 / 保存后",
         "reader": "tools/editor-bridge inspect-entity-components（**实体组件观察器**；"
                   "`template-properties verify` 不是组件观察器，故不用它）",
         "assert": "组件 delta == 0（负向断言）；保护域 entity.id/owner/configId 不变"},
        {"id": "OBS-HP-HIT", "when": "自然攻击前后",
         "channel": {"componentKey": HP_COMPONENT_KEY, "propertyOffset": HP_PROPERTY_OFFSET,
                     "hpProp": HP_PROP, "maxHpProp": MAX_HP_PROP},
         "assert": "HP **必须下降**；**HP=0 是合法值，不得当成缺失**"},
        {"id": "OBS-HP-DEATH", "when": "HP 归零后",
         "assert": "实体消失 或 hp==0；两者都用 `is not None` 判定"},
        {"id": "OBS-GIL-DIFF", "when": "unified layer 保存后",
         "requiresCtx": ["beforeGil", "afterGil"],
         "argvFromCtx": ["beforeGil", "afterGil"],
         "entry": ENTRY_FIELD_DIFF,
         "assert": "**独立目标**：field 10（节点图）必须变化；保护域（field 5/6/7）不得异常变动",
         "note": "路径由 ctx 提供（**不接受占位**）；本模块**不自己保存**，只消费总装保存前后的两份 gil"},
    ]
    return {"opCount": len(ops), "ops": ops,
            "targetFields": ["hp", "maxHp", "alive"],
            "protectionDomain": ["entity.id", "entity.owner", "entity.configId"],
            "independentTargetProven": True,
            "graphTargets": [{"campRef": i["campRef"],
                              "graphNativeName": i["graphNativeName"],
                              "currencyPort1": currency_port1_by_real_node(i)}
                             for i in graph_plan["instances"]],
            "forbidPrintStringAsCombat": True, "forbidHpMutation": True,
            # **断言器接线**（r22）：读回不是「看一眼」，而是交给具名断言器判
            "verifiers": {
                "OBS-HP-HIT": {
                    "fn": "assert_damage_observed",
                    "requires": ["before_hp 非空", "同一 trial", "after.hp < before.hp"],
                    "rejects": ["消失当伤害", "before 空集", "无明确死亡证据的消失"]},
                "OBS-HP-DEATH": {
                    "fn": "assert_damage_observed",
                    "deathEvidence": "hp==0（显式数值）或 death_evidence[id]",
                    "rejects": ["拿 disappear 顶替死亡"]},
                "OBS-COMPONENTS-DELTA": {
                    "fn": "assert_component_delta_zero",
                    "requires": ["CaptureComponents 字段级数据", "保护域 entity GUID/owner/configId"],
                    "rejects": ["指针相同但字段被改（旧实现会漏）"]},
            }}


# ------------------------------------------------ 生产战斗验收入口（r23）
PLAYTEST_DIR = "tools/playtest-control"


def _import_vitals():
    """**静态复用** `tools/playtest-control` 的真实工具（不自己造解码器）。

    * `vitals_receipt.decode_bound(run, card)` —— 完整绑定 action19 / receipt24 /
      raw `acceptance.bin`，返回重新解出的结构化结果；
    * `vitals_contract.interpretation(o, card)` —— 返回 `trialIdentityBound` 与
      逐实体的 `runtimeId / currentHp / maxHp / hpKnown / lifeState / alive / dead …`。
    """
    sys.path.insert(0, str(REPO / PLAYTEST_DIR))
    try:
        import vitals_receipt
        import vitals_contract
    except Exception as exc:  # noqa: BLE001
        raise EntryError("VITALS_TOOL_UNAVAILABLE", str(exc)) from None
    return vitals_receipt, vitals_contract


def decode_vitals_side(run_dir: str, card: dict) -> dict:
    """**重新 decode 一侧 run**（真调 `decode_bound`，不读缓存、不造值）。"""
    vr, _vc = _import_vitals()
    run = Path(run_dir)
    if not run.is_dir():
        raise EntryError("VITALS_RUN_MISSING", f"run 目录不存在：{run_dir}")
    try:
        decoded = vr.decode_bound(run, card)
    except Exception as exc:  # noqa: BLE001
        raise EntryError("VITALS_DECODE_REFUSED",
                         f"{run_dir}: {type(exc).__name__}: {exc}") from None
    if decoded.get("ok") is not True:
        raise EntryError("VITALS_NOT_ACCEPTED",
                         f"{run_dir}: ok!=True error={decoded.get('error')!r}")
    return decoded


def identity_consistency(before: dict, after: dict, *,
                         expected_operation: str = "vitals-state") -> dict:
    """**身份一致性校验**：trial / session / targetLevel / runtime 必须对得上。

    `expected_operation` 区分来源：vitals 侧是 `vitals-state`（action19），
    contact 侧是 `contact-state`（action17）—— 两者用同一套身份判据。
    """
    problems = []
    for tag, d in (("before", before), ("after", after)):
        if d.get("trialIdentityBound") is not True:
            problems.append(f"{tag}: trialIdentityBound 不是 True")
        if d.get("operation") != expected_operation:
            problems.append(f"{tag}: operation={d.get('operation')!r} "
                            f"!= {expected_operation!r}")
    if before.get("session") != after.get("session"):
        problems.append(f"session 不同：{before.get('session')} vs {after.get('session')}")
    if before.get("targetLevelId") != after.get("targetLevelId"):
        problems.append(f"targetLevel 不同：{before.get('targetLevelId')} vs "
                        f"{after.get('targetLevelId')}")
    if before.get("mode") != "play" or after.get("mode") != "play":
        problems.append("mode 不是 play")
    # **祖先 trial/cache identity（r32）**：有 `trialState` 就**必须**以它为键并逐字段相等。
    # `control_contract.py:62` 的 `interpretation_control` 产出 `trialState` —— 那才是祖先身份；
    # 只比 session+targetLevelId 会把**两个不同试玩**拼成一次验收。
    ts_b, ts_a = before.get("trialState"), after.get("trialState")
    ancestor_ok = False
    if isinstance(ts_b, dict) and isinstance(ts_a, dict):
        if json.dumps(ts_b, sort_keys=True, ensure_ascii=False) != \
                json.dumps(ts_a, sort_keys=True, ensure_ascii=False):
            problems.append("**祖先 trialState 不同**（两个不同试玩）⇒ 不得拼成一次验收")
        else:
            ancestor_ok = True
    if problems:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "vitals 身份不一致：" + "; ".join(problems[:5]))
    key = (json.dumps(ts_b, sort_keys=True, ensure_ascii=False)
           if ancestor_ok else
           json.dumps([before.get("session"), before.get("targetLevelId")],
                      ensure_ascii=False, sort_keys=True))
    return {"trialIdentityBound": True, "session": before.get("session"),
            "targetLevelId": before.get("targetLevelId"),
            "runtimeIdentity": "session/targetLevel 一致",
            "ancestorIdentityAvailable": ancestor_ok,
            "ancestorIdentityBasis": ("trialState（祖先 trial/cache）" if ancestor_ok
                                      else "session+targetLevel **回落**（无 trialState）"),
            "sameTrial": True, "trialKey": key}


def _monster_rows(decoded: dict) -> list[dict]:
    return [e for e in (decoded.get("entities") or [])
            if e.get("entityKind") == "monster"]


def hp_map(decoded: dict, ids: list[int] | None = None) -> dict:
    """从**真实实体行**取 HP（`hpKnown` 为假即不填，不猜）。"""
    out = {}
    for e in _monster_rows(decoded):
        rid = e.get("runtimeId")
        if ids is not None and rid not in ids:
            continue
        out[int(rid)] = {"hp": e.get("currentHp") if e.get("hpKnown") else None,
                         "maxHp": e.get("maxHp"),
                         "lifeState": e.get("lifeState"),
                         "lifeStateEvidence": e.get("lifeStateEvidence"),
                         "hpKnown": bool(e.get("hpKnown")),
                         "dead": e.get("dead"), "alive": e.get("alive")}
    return out


def death_evidence_from_life_state(decoded: dict, targets: list[int]) -> dict:
    """**死亡证据只认真实字段 `lifeState == 'dead'`**（r23 收紧）。

    不再接受「字典里任意真值」——必须同时满足：
      * 该 runtimeId 在**本次绑定 trial** 内被观测到；
      * `lifeState == 'dead'` 且 `lifeStateEvidence` 非空。
    """
    out = {}
    for e in _monster_rows(decoded):
        rid = e.get("runtimeId")
        if rid not in targets:
            continue
        if e.get("observedDuringBoundTrial") is not True:
            continue
        if e.get("lifeState") != "dead":
            continue
        ev = e.get("lifeStateEvidence")
        if not ev:
            continue
        out[int(rid)] = {"lifeState": "dead", "evidence": ev, "runtimeId": rid,
                         "observedDuringBoundTrial": True}
    return out


def component_payload(decoded: dict) -> dict:
    """把真实实体行整理成 `assert_component_delta_zero` 要的实体表形状。"""
    ents = []
    for e in (decoded.get("entities") or []):
        if e.get("entityKind") != "monster":
            continue
        comps = []
        for key in ("component", "properties"):
            v = e.get(key)
            if isinstance(v, list):
                comps.extend(v)
            elif isinstance(v, dict):
                comps.append(v)
            elif isinstance(v, int) and not isinstance(v, bool):
                comps.append({"id": v})
        ents.append({"id": e.get("runtimeId"), "configId": e.get("configId"),
                     "owner": e.get("entityKind"), "config": e.get("runtimeClass"),
                     "components": comps, "runtimeId": e.get("runtimeId")})
    return {"entities": ents}


def assert_combat_acceptance(*, before_run: str, after_run: str, card: dict,
                             targets: list[int] | None = None) -> dict:
    """**生产战斗验收入口**：真实 before/after run → 重新 decode → 身份校验 →
    喂 `assert_damage_observed` 与 `assert_component_delta_zero`。

    实际运行由**统一期**做；没有真实 run 数据时**明确报「无数据、未验收」**，
    **绝不拿构造值冒充**。
    """
    b = decode_vitals_side(before_run, card)
    a = decode_vitals_side(after_run, card)
    ident = identity_consistency(b, a)

    # **目标集取自 before 侧怪物**（r23 修正）：若取交集，消失的实体会从目标里
    # 悄悄掉出去 ⇒ 「消失当伤害」的漏洞会以另一种形式回流。
    ids = targets if targets else sorted({e["runtimeId"] for e in _monster_rows(b)})
    if not ids:
        raise EntryError("VITALS_NOT_ACCEPTED",
                         "before 侧没有 monster runtimeId ⇒ 无对象可核（不构造）")

    before_hp = hp_map(b, ids)
    after_hp = hp_map(a, ids)
    if not before_hp:
        raise EntryError("READBACK_ASSERTION_FAILED",
                         "before 侧没有任何 hpKnown 的怪物行 ⇒ 无法证明伤害（不构造值）")

    death = death_evidence_from_life_state(a, ids)
    damage = assert_damage_observed(
        before_hp, after_hp, expected_ids=ids,
        trial_before=ident["trialKey"], trial_after=ident["trialKey"],
        death_evidence=death)
    components = assert_component_delta_zero(component_payload(b),
                                             component_payload(a))
    return {"accepted": damage.get("verified") is True,
            "identity": ident, "targets": ids, "damage": damage,
            "componentPreservation": components,
            "deathEvidenceSource": "lifeState == 'dead'（真实字段）+ observedDuringBoundTrial",
            "beforeRun": str(before_run), "afterRun": str(after_run),
            "configIdIsNotSpawnProof": "`configuredSpawnIdentityVerified=false` ⇒ "
                                       "**configId 相同不冒充目标出生**",
            "notRunHere": "本入口在被调用时才真 decode；开发期未持有 run 数据 ⇒ 未验收"}


# ------------------------------------------------ contact-state v8 双来源（r24）
CONTACT_SCOPE = "FIXED_PLAYTEST_CONTACT"


def _import_contact():
    """**静态复用** `tools/playtest-control` 的 contact 工具（不自己写身份判定）。

    * `contact_receipt.decode_bound(run, card)` —— 绑定 action17 / receipt /
      raw `acceptance.bin`，内部走 `contact_contract.parse` + `interpretation`；
    * `contact_contract.identities(s, rows)` —— **L89-104** 的复合身份判定。
    """
    sys.path.insert(0, str(REPO / PLAYTEST_DIR))
    try:
        import contact_receipt
        import contact_contract
    except Exception as exc:  # noqa: BLE001
        raise EntryError("CONTACT_TOOL_UNAVAILABLE", str(exc)) from None
    return contact_receipt, contact_contract


def decode_contact_side(run_dir: str, card: dict) -> dict:
    """**重新 decode 一侧 contact run**（真调 `contact_receipt.decode_bound`）。"""
    cr, _cc = _import_contact()
    run = Path(run_dir)
    if not run.is_dir():
        raise EntryError("CONTACT_RUN_MISSING", f"contact run 目录不存在：{run_dir}")
    try:
        decoded = cr.decode_bound(run, card)
    except Exception as exc:  # noqa: BLE001
        raise EntryError("CONTACT_DECODE_REFUSED",
                         f"{run_dir}: {type(exc).__name__}: {exc}") from None
    if decoded.get("ok") is not True:
        raise EntryError("CONTACT_NOT_ACCEPTED",
                         f"{run_dir}: ok!=True error={decoded.get('error')!r}")
    return decoded


def _contact_rows(decoded: dict) -> list[dict]:
    return [e for e in (decoded.get("entities") or []) if not e.get("localAvatar")]


def connect_by_runtime_id(vitals_decoded: dict, contact_decoded: dict) -> dict:
    """**只按同一 `runtimeId` 连接**两来源；**绝不按 `configId` 拼接**。"""
    v = {}
    for e in (vitals_decoded.get("entities") or []):
        if e.get("entityKind") == "monster":
            v[int(e["runtimeId"])] = e
    if not v:
        raise EntryError("VITALS_NOT_ACCEPTED", "vitals 侧没有 monster row ⇒ 无法连接")
    c = {}
    for e in _contact_rows(contact_decoded):
        c[int(e["runtimeId"])] = e
    joined = sorted(set(v) & set(c))
    if not joined:
        raise EntryError("DUAL_SOURCE_NOT_CONNECTED",
                         f"两来源没有**同一 runtimeId** 的行（vitals={len(v)} "
                         f"contact={len(c)}）⇒ 不得按 configId 拼接")
    return {"joinedRuntimeIds": joined, "joinedCount": len(joined),
            "onlyInVitals": sorted(set(v) - set(c)),
            "onlyInContact": sorted(set(c) - set(v)),
            "connectionKey": "runtimeId(only)",
            "configIdJoiningForbidden": True,
            "vitalsById": v, "contactById": c}


def match_editor_guid(contact_entities: list[dict], receipts: dict) -> dict:
    """**用 `editorEntityGuid` 精确匹配本轮创建 receipt**。

    `receipts` = `{ref: editorInstanceGuid(int)}`。
    `editorEntityGuid` 只在 `identityMappingVerified is True` 时非 None（contact L103）。
    """
    by_guid = {}
    for ref, g in (receipts or {}).items():
        if isinstance(g, bool) or not isinstance(g, int):
            raise EntryError("EDITOR_GUID_INVALID", f"{ref}: 非整数 editorGUID {g!r}")
        by_guid[g] = ref
    matched, unverified, unmatched = [], [], []
    for e in contact_entities:
        g = e.get("editorEntityGuid")
        if e.get("identityMappingVerified") is not True or g is None:
            unverified.append(int(e["runtimeId"]))
            continue
        if g in by_guid:
            matched.append({"ref": by_guid[g], "editorEntityGuid": g,
                            "runtimeId": int(e["runtimeId"]),
                            "beyondEntityId": e.get("beyondEntityId"),
                            "mappingStatus": e.get("mappingStatus"),
                            "mappingIndex": e.get("mappingIndex"),
                            "reverseIndex": e.get("reverseIndex"),
                            "entryIndex": e.get("entryIndex")})
        else:
            unmatched.append({"runtimeId": int(e["runtimeId"]),
                              "editorEntityGuid": g,
                              "why": "不在本次创建 receipt 的 GUID 集里"})
    return {"matched": matched, "matchedCount": len(matched),
            "unverifiedMappingRuntimeIds": unverified, "unmatched": unmatched,
            "matchKey": "editorEntityGuid(精确) → 创建 receipt ref",
            "configIdNotUsed": True}


def assert_boundary_fields(contact_decoded: dict, contact_entities: list[dict],
                           targets: list[int]) -> dict:
    """**边界字段不得被绕过**（r24 / **GAP-4 修正**）。

    * 目标行必须**逐 row** `belongsToBoundTrial is True`（`None` 与 `false` 都拒）；
    * **GAP-4**：**不得**用顶层 `targetLevelSpawnMembershipVerified`（全页 bool）当判据 ——
      它表达的是「全页所有普通行都 verified」，而本模块只关心**被精确 GUID 选中的 target**。
      **非目标普通实体归属 unknown 不得让真实唯一目标假失败**；
    * 目标行还须 `targetLevelSpawnMembershipVerified is True` 且 `sourceInstance` 非空
      （`directory_contract.py:42` 的三字段是逐 row 的）。
    """
    tgt = {int(t) for t in targets}
    seen: set[int] = set()
    bad_trial: list[int] = []
    bad_spawn: list[int] = []
    bad_inst: list[int] = []
    for e in contact_entities:
        rid = int(e["runtimeId"])
        if rid not in tgt:
            continue
        seen.add(rid)
        if e.get("belongsToBoundTrial") is not True:
            bad_trial.append(rid)
        if e.get("targetLevelSpawnMembershipVerified") is not True:
            bad_spawn.append(rid)
        if e.get("sourceInstance") in (None, {}, [], ""):
            bad_inst.append(rid)
    missing_targets = sorted(tgt - seen)
    top_bool = contact_decoded.get("targetLevelSpawnMembershipVerified")
    if bad_trial or bad_spawn or bad_inst or missing_targets:
        raise EntryError(
            "TARGET_MEMBERSHIP_UNVERIFIED",
            f"目标逐 row 校验未过：`belongsToBoundTrial` 非 True {bad_trial[:5]}；"
            f"`targetLevelSpawnMembershipVerified` 非 True {bad_spawn[:5]}；"
            f"`sourceInstance` 缺失 {bad_inst[:5]}；"
            f"未在 contact 实体里找到的目标 {missing_targets[:5]}。"
            f"（顶层全页 bool 观测值={top_bool!r}，但**只对精确 GUID 选中的 target 逐 row 要求**，"
            "非目标普通实体归属 unknown 不影响本判定）")
    return {"belongsToBoundTrial": True, "targetLevelSpawnMembershipVerified": True,
            "perTargetVerifiedCount": len(seen),
            "topLevelBoolUsedAsCriterion": False,
            "topLevelBoolObserved": top_bool,
            "nonTargetRowsDoNotAffectVerdict": True,
            "membershipEvidence": "逐 target 精确 GUID 命中且三字段均真；顶层 bool 仅记录不作判据"}


#: contact 分页上限（`contact_contract.py:6` ROW_CAPACITY=129 ⇒ 每页最多 128 普通实体）
MAX_CONTACT_PAGES = 512


def _page_of(decoded: dict) -> dict:
    """`pageStart`/`pageEnd`/`next` 都是**回执头里的原生字段**（contact_contract.py:10/L78/L113），
    不是调用方自行编造的值 —— 本函数只**读**它们。"""
    p = decoded.get("page") or {}
    return {"start": p.get("start"), "end": p.get("end"), "next": p.get("next"),
            "dictionaryCount": p.get("dictionaryCount"),
            "dictionaryVersion": p.get("dictionaryVersion")}


def walk_contact_pages(read_page, *, card: dict,
                       max_pages: int | None = None) -> dict:
    """**每页一次新的原生读取**，循环跟随 `page.next` 直到 `None`。

    ⚠️ **不是**在单个 payload 里本地迭代：`pageStart`/`pageEnd` 来自**每次回执头**
    （`contact_contract.py:10` HEADER 含 `pageStart`/`pageEnd`；`:78` 校验
    `0<=pageStart<=pageEnd<=65536`；`:113` `next = pageEnd if pageEnd < entityCount else None`）。
    所以翻页 = **再发起一次 contact-state 读取、拿新回执**；本函数的 `read_page(i, start, card)`
    就是**第 i 次读取**的入口（统一期接真实读取命令；每次读取**各自落 journal**）。

    保护（任一即**具名拒**，绝不死循环 —— 每页是一次真实读取，死循环会真的重复发命令）：
      * 页数上限 ⇒ `CONTACT_PAGE_CAP_EXCEEDED`；
      * `next` **不前进**（`<= start`）⇒ `CONTACT_PAGE_NOT_ADVANCING`；
      * `next` **自环/重复**，或 `page.start` 重复 ⇒ `CONTACT_PAGE_CYCLE`；
      * 回执的 `page.start` 与本次请求不符 ⇒ `CONTACT_PAGE_MISMATCH`；
      * `next` 仍有但页数耗尽/读取器报告读完 ⇒ `CONTACT_PAGES_INCOMPLETE`。
    跨页**按 `runtimeId` 去重**；同一 `runtimeId` 跨页**信息冲突**（含 `entryIndex` 不一致）
    ⇒ `CONTACT_PAGE_CONFLICT`。页内唯一性由契约 L85 保证，这里不重复造。
    """
    cap = max_pages or MAX_CONTACT_PAGES
    start = card.get("pageStart")
    if not isinstance(start, int) or isinstance(start, bool):
        raise EntryError("CONTACT_PAGE_INVALID", "card.pageStart 必须是整数")
    # **r32：强制 page0 起** —— 从中间页起就等于放弃前半页，不能宣称完整
    if start != 0:
        raise EntryError("CONTACT_PAGE_NOT_ZERO",
                         f"card.pageStart={start} != 0 ⇒ **必须从 page0 起**"
                         "（从中间页起不得宣称完整）")
    pages: list[dict] = []
    _runs_seen: set = set()
    _snapshot_key = None
    entities: list[dict] = []
    seen: dict[int, dict] = {}
    visited: set[int] = set()
    first: dict | None = None
    i = 0
    while True:
        if len(pages) >= cap:
            raise EntryError("CONTACT_PAGE_CAP_EXCEEDED",
                             f"翻页超过上限 {cap} 页（疑似不收敛）——"
                             "每页都是一次真实读取，已停止以免重复发命令")
        # ---------- 第 i 次**新的读取**（每次各自 journal）
        decoded = read_page(i, start, card)
        if first is None:
            first = decoded
        pg = _page_of(decoded)
        if pg["start"] != start:
            raise EntryError("CONTACT_PAGE_MISMATCH",
                             f"第 {i} 次读取的回执 page.start={pg['start']!r} != 请求 {start}")
        if pg["start"] in visited:
            raise EntryError("CONTACT_PAGE_CYCLE",
                             f"page.start={pg['start']} 重复出现 ⇒ 自环/环")
        visited.add(pg["start"])
        pages.append({"readIndex": i, **pg})
        # **r31 ②：同一 run 不得复用**
        _run_tag = decoded.get("run") or decoded.get("runDir")
        if _run_tag is not None:
            if _run_tag in _runs_seen:
                raise EntryError("CONTACT_PAGE_RUN_REUSED",
                                 f"同一个 run 被重复读取：{_run_tag} "
                                 f"（page.start={pg['start']}）⇒ 每页必须是一次新读取")
            _runs_seen.add(_run_tag)
        # **r31 ②：dictionaryCount/version 与 trial 身份跨页必须恒定**
        # **GAP-1/GAP-2 修正**：回执没有顶层 `nativeVersion`；真实版本在
        # `nativeReceipt.version`。跨页键改用该真实路径，避免拿 None 恒等于
        # None 造成"版本从未变化"的假恒定。
        _nr_page = decoded.get("nativeReceipt") or {}
        _key = (pg["dictionaryCount"], pg["dictionaryVersion"],
                json.dumps(decoded.get("session"), sort_keys=True),
                decoded.get("targetLevelId"), _nr_page.get("version"),
                _nr_page.get("operation"))
        if _snapshot_key is None:
            _snapshot_key = _key
        elif _key != _snapshot_key:
            raise EntryError("CONTACT_PAGE_DICTIONARY_CHANGED",
                             f"跨页快照身份变化：{_snapshot_key} → {_key}"
                             "（dictionaryCount/version/session/targetLevel 必须恒定）"
                             "⇒ 立即停，**不得拼凑快照**")
        for e in (decoded.get("entities") or []):
            rid = int(e["runtimeId"])
            if rid in seen:
                prev = seen[rid]
                if prev != e:
                    # `entryIndex` 不一致是最典型的跨页冲突信号（L86 保证页内一致）
                    raise EntryError("CONTACT_PAGE_CONFLICT",
                                     f"runtimeId={rid} 跨页信息冲突："
                                     f"entryIndex {prev.get('entryIndex')} vs "
                                     f"{e.get('entryIndex')}（第 {i} 次读取）")
                continue                                  # 完全重复 ⇒ 去重
            seen[rid] = e
            entities.append(e)
        nxt = pg["next"]
        if nxt is None:
            break
        # **先判环**（指回已访问页 ⇒ CYCLE，比"不前进"更具体）
        if isinstance(nxt, int) and not isinstance(nxt, bool) and nxt in visited:
            raise EntryError("CONTACT_PAGE_CYCLE", f"page.next={nxt} 指回已访问页")
        # 再判前进性：`next` 必须**不小于本页 pageEnd**（契约 L113 是 next=pageEnd），
        # 且严格大于 start —— 否则「倒退到页内」也会被放过。
        if not isinstance(nxt, int) or isinstance(nxt, bool) \
                or nxt <= pg["start"] or (pg["end"] is not None and nxt != pg["end"]):
            raise EntryError("CONTACT_PAGE_NOT_ADVANCING",
                             f"page.next={nxt!r} 必须**精确等于** pageEnd={pg['end']}"
                             f"（start={pg['start']}）⇒ 跳页/倒退一律拒")
        start = nxt
        i += 1
    return {"entities": entities, "pageCount": len(pages), "pages": pages,
            "reads": len(pages), "dedupedBy": "runtimeId", "maxPages": cap,
            "firstDecoded": first,
            "pagingMode": "ONE_NEW_NATIVE_READ_PER_PAGE",
            "pagingFollowed": "page.next → 直到 None", "noInfiniteLoop": True}


def run_dir_page_reader(page_runs, decoder=None):
    """**默认读取器**：`page_runs` 里**一个 run 目录 = 一次真实读取的回执**。

    统一期应把它换成**真跑读取命令**的读取器（每次读取产生新 run + journal）；
    本模块只负责「按 `next` 逐次驱动 + 校验 + 去重 + 冲突拒」。
    """
    runs = list(page_runs or [])

    def read_page(i, start, card):
        if i >= len(runs):
            raise EntryError("CONTACT_PAGES_INCOMPLETE",
                             f"page.next 尚未为 None（要读 page.start={start}）"
                             f"但只给了 {len(runs)} 次读取的回执")
        decode = decoder or decode_contact_side
        return decode(runs[i], dict(card, pageStart=start))
    return read_page


#: **每页 journal**（生产路径**默认启用**；r27）
PAGE_JOURNAL_DIR = REPO / ".runtime-verify/combat-page-journal"
_UNSET = object()


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


#: journal 单文件上限（默认 4 MiB）；超限 **fail-closed**，不默默截断
JOURNAL_MAX_BYTES = 4 * 1024 * 1024


def _journal_write(path: Path, payload: dict, *,
                   max_bytes: int | None = None,
                   truncate_field: str | None = None) -> Path:
    """**写 journal 的 fail-closed 层**（r28/r29）：序列化 + 写入整体包住。

    * **序列化失败**（`TypeError`/`ValueError`，如不可序列化对象）⇒
      `PAGE_JOURNAL_SERIALIZE_FAILED`（带目标路径 + 原因）；
    * **写入失败**（`OSError`，磁盘满/目录不可写）⇒ `PAGE_JOURNAL_WRITE_FAILED`；
    * **超 `maxBytes`** ⇒ `PAGE_JOURNAL_TOO_LARGE`（带 `originalBytes` / `limit`）。

    **截断策略写明**：默认**不截断、fail-closed**（超限即拒）；只有调用方显式给
    `truncate_field` 时才截断该字段，且**必写 `truncated=true` + `originalBytes`**
    —— **绝不默默截断**（默默截断等于伪造完整性）。两类失败都**仍立即停、不重放**。
    """
    limit = JOURNAL_MAX_BYTES if max_bytes is None else max_bytes
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    except (TypeError, ValueError) as exc:
        raise EntryError(
            "PAGE_JOURNAL_SERIALIZE_FAILED",
            f"journal 序列化失败：目标={path}；原因={type(exc).__name__}: {exc}；"
            "**立即停、不重放**") from None
    raw = text.encode("utf-8")
    if truncate_field and truncate_field in payload and len(raw) > limit:
        original = len(raw)
        keep = max(0, limit // 2)
        payload = dict(payload)
        payload[truncate_field] = payload[truncate_field][:keep]
        payload["truncated"] = True
        payload["originalBytes"] = original
        payload["limitBytes"] = limit
        payload["truncationPolicy"] = (f"字段 {truncate_field} 保留前 {keep} 字符；"
                                      "已标 truncated=true 与原长度")
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        raw = text.encode("utf-8")
    if len(raw) > limit:
        raise EntryError(
            "PAGE_JOURNAL_TOO_LARGE",
            f"journal 超过上限：目标={path}；originalBytes={len(raw)}；limit={limit}；"
            "**策略：默认不截断、fail-closed**（要截断须显式指定并标 truncated）")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError as exc:
        raise EntryError(
            "PAGE_JOURNAL_WRITE_FAILED",
            f"写 journal 失败：目标={path}；原因={type(exc).__name__}: {exc}；"
            "**立即停、不重放**（证据没落盘就不能假装记过了）") from None
    return path


def _exclusive_journal_write(path: Path, payload: dict, *,
                             max_bytes: int | None = None,
                             truncate_field: str | None = None) -> Path:
    """① **独占写**：同路径第二次写 ⇒ 具名 `PAGE_JOURNAL_DUPLICATE_WRITE`。

    不允许悄悄覆盖 —— 覆盖会把 before 侧原件毁掉。
    """
    if path.exists():
        raise EntryError("PAGE_JOURNAL_DUPLICATE_WRITE",
                         f"journal 目标已存在，**拒绝覆盖**：{path}；"
                         "before/after 必须用彼此独立的目录与操作 ID")
    limit = JOURNAL_MAX_BYTES if max_bytes is None else max_bytes
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    except (TypeError, ValueError) as exc:
        raise EntryError("PAGE_JOURNAL_SERIALIZE_FAILED",
                         f"journal 序列化失败：目标={path}；"
                         f"原因={type(exc).__name__}: {exc}") from None
    raw = text.encode("utf-8")
    if truncate_field and truncate_field in payload and len(raw) > limit:
        keep = max(0, limit // 2)
        payload = dict(payload)
        payload[truncate_field] = payload[truncate_field][:keep]
        payload.update(truncated=True, originalBytes=len(raw), limitBytes=limit,
                       truncationPolicy=f"字段 {truncate_field} 保留前 {keep} 字符")
        raw = (json.dumps(payload, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if len(raw) > limit:
        raise EntryError("PAGE_JOURNAL_TOO_LARGE",
                         f"journal 超限：目标={path}；originalBytes={len(raw)}；"
                         f"limit={limit}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as fh:            # **独占创建**：已存在即抛
            fh.write(raw)
    except FileExistsError:
        raise EntryError("PAGE_JOURNAL_DUPLICATE_WRITE",
                         f"journal 目标已存在（竞态），**拒绝覆盖**：{path}") from None
    except OSError as exc:
        raise EntryError("PAGE_JOURNAL_WRITE_FAILED",
                         f"写 journal 失败：目标={path}；"
                         f"原因={type(exc).__name__}: {exc}") from None
    return path


def journaling_page_reader(inner, journal_dir, run_id: str, side: str, *,
                           max_bytes: int | None = None):
    """① **后侧不得覆盖前侧原件**：目录 = `<base>/<runId>/<side>/`，且**独占写**。

    `run_id` 与 `side`（`before`/`after`）**必填** —— 不允许无 run_id 退化；
    要「不落 journal」只能显式 `journal_dir=False`（产物标 `journalPerPage=false`
    且**结论被门住**）。
    """
    if not run_id:
        raise EntryError("PAGE_JOURNAL_SCOPE_REQUIRED",
                         "journaling 需要 runId（低层写手必填；"
                         "无 runId 时由 `contact_side` 关闭 journal 并门住结论）")
    if side not in ("before", "after"):
        raise EntryError("PAGE_JOURNAL_SCOPE_REQUIRED",
                         f"side 必须是 before/after，实得 {side!r}（防两侧共用目录）")
    jd = Path(journal_dir) / str(run_id) / str(side)
    jd.mkdir(parents=True, exist_ok=True)
    journaling_page_reader.dir = jd
    journaling_page_reader.side = side

    def read_page(i, start, card):
        stem = f"{i:03d}-page{start}"
        intent = jd / f"{stem}-intent.json"
        _exclusive_journal_write(intent, {
            "pageIndex": i, "pageStart": start, "state": "INTENT",
            "runId": run_id, "side": side, "runScoped": True,
            "cardPageStart": card.get("pageStart"), "startedAt": _now_iso(),
        }, max_bytes=max_bytes)
        try:
            out = inner(i, start, card)
        except Exception as exc:  # noqa: BLE001
            _exclusive_journal_write(jd / f"{stem}-failed.json", {
                "pageIndex": i, "pageStart": start, "state": "FAILED",
                "runId": run_id, "side": side, "errorType": type(exc).__name__,
                "error": str(exc), "intentJournal": str(intent),
                "replayAllowed": False, "argvSource": "reader",
                "stopRule": "失败即停：后续页不再读取、不重放",
                "failedAt": _now_iso(),
            }, max_bytes=max_bytes)
            raise
        rec = {"pageIndex": i, "pageStart": start, "state": "RESULT",
               "runId": run_id, "side": side, "runScoped": True,
               "ok": (out or {}).get("ok") if isinstance(out, dict) else None,
               "finishedAt": _now_iso(), "intentJournal": str(intent),
               "replayAllowed": False}
        if isinstance(out, dict) and out.get("argv"):
            rec["argv"] = list(out["argv"])
            rec["argvSource"] = "reader-provided"
        else:
            rec["argvSource"] = "reader"
        if isinstance(out, dict):
            for k in ("returncode", "stdoutFull", "stderrFull"):
                if k in out:
                    rec[k] = out[k]
            if "stdoutFull" in out:
                rec["outputKind"] = "command"
            else:
                rec["outputKind"] = "decoded"
                rec["decodedFull"] = json.dumps(out, ensure_ascii=False)
        else:
            rec["outputKind"] = "other"
            rec["decodedFull"] = repr(out)
        path = _exclusive_journal_write(jd / f"{stem}-result.json", rec,
                                        max_bytes=max_bytes,
                                        truncate_field="decodedFull")
        if isinstance(out, dict):
            out = dict(out, pageJournal=str(path), pageIndex=i, pageStart=start,
                       journalSide=side)
        return out
    return read_page


def contact_side(page_runs, card: dict, decoder=None,
                 read_page=None, max_pages: int | None = None,
                 journal_dir=_UNSET, run_id: str | None = None,
                 side: str | None = None) -> dict:
    """contact 一侧统一入口：**无论单页多页都走 `walk_contact_pages`**。

    **r31**：journaling 开启时 `run_id` 与 `side`（`before`/`after`）**必填** ——
    目录 `<base>/<runId>/<side>/`，**两侧互不覆盖、独占写**。
    无 `run_id`/`side` ⇒ **具名 `PAGE_JOURNAL_SCOPE_REQUIRED`**（不再退化）。
    要关掉 journal 只能显式 `journal_dir=False` ⇒ `journalPerPage=false` +
    `journalDegraded=true`，且**结论被门住**（不得称可独立复核）。
    """
    runner = read_page or run_dir_page_reader(
        page_runs if isinstance(page_runs, (list, tuple)) else [page_runs], decoder)
    if journal_dir is _UNSET:
        base, journal_per_page, degraded = PAGE_JOURNAL_DIR, True, False
    elif journal_dir:
        base, journal_per_page, degraded = Path(journal_dir), True, False
    else:
        base, journal_per_page, degraded = None, False, True
    run_scoped = False
    jd = None
    if journal_per_page and run_id and side:
        # r31：runId + side 必填 ⇒ `<base>/<runId>/<side>/`，两侧互不覆盖
        runner = journaling_page_reader(runner, base, run_id=run_id, side=side)
        jd = journaling_page_reader.dir
        run_scoped = True
    elif journal_per_page:
        # **r32**：无 runId/side ⇒ **dry-run 仍可跑**，但关掉 journal 并标降级
        # ⇒ `independentlyReviewable=false`、结论被门住（不得称可独立复核）
        journal_per_page = False
        degraded = True
        base = None
    walked = walk_contact_pages(runner, card=card, max_pages=max_pages)
    first = walked["firstDecoded"] or {}
    return {**first, "entities": walked["entities"],
            "page": {"start": walked["pages"][0]["start"] if walked["pages"] else None,
                     "end": walked["pages"][-1]["end"] if walked["pages"] else None,
                     "next": None, "pages": walked["pageCount"],
                     "dictionaryCount": (walked["pages"][-1]["dictionaryCount"]
                                         if walked["pages"] else None)},
            "allPages": walked["pages"], "readsPerformed": walked["reads"],
            "dedupedRuntimeIdCount": len(walked["entities"]),
            "pagingMode": walked["pagingMode"], "pagingVerified": True,
            "journalPerPage": journal_per_page,
            "pageJournalDir": str(jd) if jd else None,
            "journalRunScoped": run_scoped,
            "journalRunId": run_id,
            "journalDegraded": degraded,
            # **结论门控**（r29）：没有 run 归属的 journal **不能**称「可独立复核」
            "independentlyReviewable": bool(journal_per_page and run_scoped),
            "auditBlockers": ([] if (journal_per_page and run_scoped) else
                              (["journalPerPage=false"] if not journal_per_page
                               else ["journalRunScoped=false"])),
            "journalNote": (
                (f"每页一条 intent + 一条 result（含完整 output）；按 runId={run_id} 分子目录"
                 if run_scoped else
                 "每页一条 intent + 一条 result；**无 runId ⇒ 未按 run 分子目录"
                 "（journalRunScoped=false）**")
                if journal_per_page else
                "**显式降级**：本次没有每页 journal（journalPerPage=false）")}


def assert_behaviour_chain(*, before_rows: list[dict], after_rows: list[dict],
                           template_kinds: set[int] | None,
                           targets: list[int],
                           graph_drop_configured: bool | None = None) -> dict:
    """**遭遇链五段的生产断链修补**：出生 → 仇恨 → 追击 → 受击 → 死亡 → 掉落。

    为什么需要它：此前 `production_entry` 只覆盖 出生(creature-create) / 受击
    (HitDetection+Combat) / 死亡(lifeState) / 掉落(DropStuff+currency)，
    **仇恨(Enmity kind 26) 与 追击(FollowMove kind 9) 在验收链里零承载** ⇒
    链路在"出生之后、受击之前"是断的。

    本函数**不伪造实机效果**，只做两件可离线/可回执化的事：
      1. **模板承载面**：`template_kinds` 必须含 26(Enmity) 与 9(FollowMove) ——
         它们随 prefab 自带，不在运行时挂载；缺即 `missing`。
      2. **运行观测面**：追击用**前后位置差**作证据（位置来自 before/after 回执行）；
         仇恨用威胁/目标获取证据（`threat`/`enmity`/`targetRuntimeId` 字段）；
         拿不到就记 **`unknown`，绝不当通过**。

    返回每段 `observed` / `unknown` / `missing`，并给 `chainComplete` 与
    `blockers`；**任一 `unknown`/`missing` 都会进结论门控**。
    """
    tgt = {int(t) for t in targets}
    kinds = set(int(k) for k in (template_kinds or ()))
    # **按 `behaviour-config.json` 的真实 carrier 政策**（已 accepted 的结论，不重新发明）：
    #   approach(仇恨)  TEMPLATE_NATIVE [26]
    #   chase(追击)     TEMPLATE_NATIVE [9]
    #   attack(攻击)    TEMPLATE_NATIVE [12,18,11,20]
    #   hit(受击)       NODE_GRAPH     [19]
    #   death(死亡)     NODE_GRAPH     [18]
    #   drop(掉落)      **NODE_GRAPH_PARTIAL** ⇒ 交付靠图侧 727 货币线，
    #                   **不是** 37 DropStuff 组件
    #   prefab-record-groups [30,27,37,42] = **NOT_REQUIRED**
    # ⇒ 早期版本把 37 当"模板必须自带"是**错的**：既有 accepted 结论已记
    #   `ABSENT_from_allFour["37"]` 且判 NOT_REQUIRED；掉落由 727 交付。
    template = {
        "Enmity(aggro,kind26)": 26 in kinds,
        "FollowMove(chase,kind9)": 9 in kinds,
        "HitDetection(hit,kind12)": 12 in kinds,
        "Combat(hit/death,kind18)": 18 in kinds,
        "DropStuff(kind37,NOT_REQUIRED)": 37 in kinds,
    }
    by_id_b = {int(e["runtimeId"]): e for e in (before_rows or [])
               if isinstance(e, dict) and "runtimeId" in e}
    by_id_a = {int(e["runtimeId"]): e for e in (after_rows or [])
               if isinstance(e, dict) and "runtimeId" in e}

    def _pos(e):
        p = e.get("position") if isinstance(e, dict) else None
        if isinstance(p, (list, tuple)) and len(p) == 3:
            try:
                return [float(p[0]), float(p[1]), float(p[2])]
            except (TypeError, ValueError):
                return None
        return None

    moved: list[int] = []
    chase_unknown: list[int] = []
    for rid in sorted(tgt):
        b, a2 = by_id_b.get(rid), by_id_a.get(rid)
        pb = _pos(b) if b else None
        pa = _pos(a2) if a2 else None
        if pb is None or pa is None:
            chase_unknown.append(rid)
        elif any(abs(pb[i] - pa[i]) > 1e-6 for i in range(3)):
            moved.append(rid)

    aggro_evidence = [
        rid for rid in sorted(tgt)
        if (by_id_a.get(rid) or {}).get("threat") is not None
        or (by_id_a.get(rid) or {}).get("enmity") is not None
        or (by_id_a.get(rid) or {}).get("targetRuntimeId") is not None
    ]

    status = {
        "spawn": "observed" if by_id_b and by_id_a else "unknown",
        "aggro": ("observed" if aggro_evidence
                  else ("missing" if not template["Enmity(aggro,kind26)"] else "unknown")),
        "chase": ("observed" if moved
                  else ("missing" if not template["FollowMove(chase,kind9)"] else "unknown")),
        # hit/death 是 NODE_GRAPH 承载：模板带 19/18 是**必要不充分**，
        # 图侧接线另计；这里只报模板面，运行面必须由 before/after 回执给结论。
        "hit": "missing" if not (template["HitDetection(hit,kind12)"]
                                 or template["Combat(hit/death,kind18)"]) else "unknown",
        "death": "missing" if not template["Combat(hit/death,kind18)"] else "unknown",
        # **drop 是 NODE_GRAPH_PARTIAL**：判定看**图侧 727 货币线是否配置**
        # （不是看模板有没有 37）。graph_drop_configured 由调用方从图/绑定读取。
        "drop": ("missing" if graph_drop_configured is False
                 else ("observed" if graph_drop_configured is True else "unknown")),
    }
    blockers = [f"behaviourChain:{k}={v}" for k, v in status.items()
                if v in ("unknown", "missing")]
    return {"templateCarries": template,
            "status": status,
            "aggroEvidenceRuntimeIds": aggro_evidence,
            "chaseMovedRuntimeIds": moved,
            "chaseUnknownRuntimeIds": chase_unknown,
            "chainComplete": not blockers,
            "blockers": blockers,
            "notFaked": "仇恨/追击无证据时记 unknown，不以模板自带或字段存在替代实机观测"}


def assert_dual_source_identity(*, before_vitals: str, after_vitals: str,
                                before_contact, after_contact,
                                vitals_card: dict, contact_card: dict,
                                receipts: dict | None = None,
                                contact_decoder=None,
                                before_contact_reader=None,
                                after_contact_reader=None,
                                driver: dict | None = None,
                                template_kinds: set[int] | None = None,
                                graph_drop_configured: bool | None = None,
                                journal_dir=_UNSET, run_id: str | None = None) -> dict:
    """**vitals + contact 双来源读回**（r24）+ **contact 每页一次新读取的分页**（r26）。

    `before_contact` / `after_contact` 可为**单个 run** 或**有序 run 列表**（一页一个）；
    也可直接给 `*_contact_reader`（统一期接真实读取命令）。两源都 decode、都做身份/trial
    稳定连接校验；**只按 runtimeId 连接**、**按 editorEntityGuid 精确匹配**（翻页后仍做）、
    **边界字段具名拒绝**。
    """
    # **生产接线（本轮收口）**：给了 `driver`（session / targetLevelId /
    # previousRun / execute / prepared / queue）时，用 `native_card_reader`
    # 作为 contact 的读取器 ⇒ **真正调用 `invoke_native_card`**（三步驱动）。
    # 这样 `invoke_native_card` 不再是「只有 def、无人调用」的 helper。
    if driver is not None:
        _drv = {"session": driver["session"],
                "target_level": int(driver["targetLevelId"]),
                "previous_run": driver.get("previousRun") or "",
                "execute": bool(driver.get("execute")),
                "prepared": driver.get("prepared"),
                "queue": driver.get("queue")}
        if before_contact_reader is None:
            before_contact_reader = native_card_reader(**_drv)
        if after_contact_reader is None:
            after_contact_reader = native_card_reader(**_drv)
    vb = decode_vitals_side(before_vitals, vitals_card)
    va = decode_vitals_side(after_vitals, vitals_card)
    # **r31**：两侧各自 `side`，目录 `<base>/<runId>/<before|after>/` ⇒ 后侧不覆盖前侧原件
    cb = contact_side(before_contact, contact_card, contact_decoder,
                      read_page=before_contact_reader, journal_dir=journal_dir,
                      run_id=run_id, side="before")
    ca = contact_side(after_contact, contact_card, contact_decoder,
                      read_page=after_contact_reader, journal_dir=journal_dir,
                      run_id=run_id, side="after")
    # **v8/v9 分流**：v9 走 `assert_v9_consumer`；v8 contact-state 保持 unknown
    for tag, d in (("before", cb), ("after", ca)):
        reject_v8_fields_as_v9(d, f"{tag}-contact")
    if (cb.get("operation") == TRIAL_ENTITIES_OP
            or ca.get("operation") == TRIAL_ENTITIES_OP):
        v9_b = None if cb.get("operation") != TRIAL_ENTITIES_OP else \
            assert_v9_consumer(cb, "before-contact")
        v9_a = None if ca.get("operation") != TRIAL_ENTITIES_OP else \
            assert_v9_consumer(ca, "after-contact")

    v_ident = identity_consistency(vb, va, expected_operation="vitals-state")
    c_ident = identity_consistency(cb, ca, expected_operation="contact-state")
    if v_ident["session"] != c_ident["session"] \
            or v_ident["targetLevelId"] != c_ident["targetLevelId"]:
        raise EntryError("DUAL_SOURCE_NOT_CONNECTED",
                         f"vitals 与 contact 不是同一 trial："
                         f"{v_ident['trialKey']} vs {c_ident['trialKey']}")

    link_b = connect_by_runtime_id(vb, cb)
    link_a = connect_by_runtime_id(va, ca)
    targets = sorted(set(link_b["joinedRuntimeIds"]) & set(link_a["joinedRuntimeIds"]))
    if not targets:
        raise EntryError("DUAL_SOURCE_NOT_CONNECTED", "前后两次都没有共同的 runtimeId 目标")

    # **翻页后仍精确匹配 editorEntityGuid**（累积全页 entities）
    guid_b = match_editor_guid(_contact_rows(cb), receipts or {})
    guid_a = match_editor_guid(_contact_rows(ca), receipts or {})

    boundary = assert_boundary_fields(ca, _contact_rows(ca), targets)

    # **遭遇链五段修补（真实断链）**：仇恨(Enmity26)/追击(FollowMove9) 此前在验收链
    # 零承载。这里逐段给 observed/unknown/missing，**unknown 与 missing 都进门控**。
    chain = assert_behaviour_chain(
        before_rows=_contact_rows(cb), after_rows=_contact_rows(ca),
        template_kinds=template_kinds, targets=targets,
        graph_drop_configured=graph_drop_configured)

    damage = assert_damage_observed(
        hp_map(vb, targets), hp_map(va, targets), expected_ids=targets,
        trial_before=v_ident["trialKey"], trial_after=v_ident["trialKey"],
        death_evidence=death_evidence_from_life_state(va, targets))
    components = assert_component_delta_zero(component_payload(vb),
                                             component_payload(va))
    # **结论门控**（r29/r33）：journal 无 run 归属 **或** 无祖先 trial/cache 身份
    # ⇒ **不得声称可独立复核/已验证**（dry-run 仍可跑，但 verified 必须 false）
    reviewable = bool(cb.get("independentlyReviewable")
                      and ca.get("independentlyReviewable"))
    blockers = sorted(set((cb.get("auditBlockers") or [])
                          + (ca.get("auditBlockers") or [])))
    ancestor_ok = bool(v_ident.get("ancestorIdentityAvailable")
                       and c_ident.get("ancestorIdentityAvailable"))
    if not ancestor_ok:
        blockers = sorted(set(blockers) | {"ancestorIdentityUnavailable"})
    # **遭遇链门控**：仇恨/追击等段为 unknown 或 missing 时，**不得判 verified**
    # （unknown 不是通过；模板自带也不等于实机观测到）。
    chain_ok = bool(chain.get("chainComplete"))
    if not chain_ok:
        blockers = sorted(set(blockers) | set(chain.get("blockers") or []))
    verified = ((damage.get("verified") is True) and reviewable
                and ancestor_ok and chain_ok)
    return {"accepted": verified,
            "verified": verified,
            "independentlyReviewable": reviewable,
            "ancestorIdentityAvailable": ancestor_ok,
            "behaviourChain": chain,
            "behaviourChainComplete": chain_ok,
            "auditBlockers": [] if verified else blockers,
            "conclusionGate": (
                "journal 有 run 归属 + 祖先 trial/cache 身份可用 ⇒ 结论可独立复核"
                if verified else
                "**结论被门住**："
                + ("无祖先 trialState（回落 session+targetLevel）；" if not ancestor_ok else "")
                + ("" if reviewable else "journal 无 run 归属；")
                + "damage 计算仅作参考，**不得声称已验证**"),
            "sources": ["vitals-state", "contact-state"],
            "vitalsIdentity": v_ident, "contactIdentity": c_ident,
            "crossSourceSameTrial": True,
            "pagination": {"mode": "ONE_NEW_NATIVE_READ_PER_PAGE",
                           "beforeReads": cb.get("readsPerformed"),
                           "afterReads": ca.get("readsPerformed"),
                           "followed": "page.next → 直到 None",
                           "dedupedBy": "runtimeId", "maxPages": MAX_CONTACT_PAGES},
            "connection": {"key": "runtimeId(only)",
                           "configIdJoiningForbidden": True,
                           "before": link_b["joinedRuntimeIds"],
                           "after": link_a["joinedRuntimeIds"], "targets": targets},
            "editorGuidMatchBefore": guid_b, "editorGuidMatchAfter": guid_a,
            "boundary": boundary, "damage": damage,
            "componentPreservation": components,
            "deathEvidenceSource": "lifeState == 'dead'（真实字段）",
            "note": "vitals 出 HP/生命状态；contact 出 runtimeId↔editorEntityGuid 双向映射；"
                    "**翻页后仍按 editorEntityGuid 精确匹配**；"
                    "**两源只按 runtimeId 连接，绝不按 configId 拼接**"}


# ------------------------------------------------ ⑤ v9 消费者 / ⑥ 原生卡调用器
TRIAL_ENTITIES_OP = "trial-entities"
TRIAL_ENTITIES_OP_ID = 18
TRIAL_ENTITIES_NATIVE_VERSION = 8
TRIAL_ENTITIES_PREPARED = "prepared-v9"
PLAYTEST_CLI = "tools/playtest-control/cli.py"


def native_card_argv(*, operation: str, previous_run: str, page_start: int,
                     session: str, target_level: int,
                     extra: list[str] | None = None) -> list[str]:
    """⑥ **固定原生卡 argv（r32：按 `cli.py` 真实 argparse 核对）**。

    `cli.py:75` 的 `prepare` 真参数是 **`--session`（required）**、`--target-level`、
    `--operation`（choices 含 `trial-entities`）、`--previous-run`、`--page-start`。
    `DIRECTORY-NATIVE.md:6` 的命令式也带 `--session SESSION.json --target-level LEVEL`。
    ⇒ 本函数**强制** `session` 与 `target_level`；缺即具名拒，不拼残缺 argv。
    """
    missing = [n for n, v in (("session", session),
                              ("target_level", target_level)) if v in (None, "", 0)]
    if missing:
        raise EntryError("NATIVE_CARD_ARGV_INCOMPLETE",
                         f"缺 {missing}；`cli.py prepare` 的 `--session` 是 required、"
                         "`--target-level` 必给（按真实 argparse）")
    return [sys.executable, "-B", str(REPO / PLAYTEST_CLI), "prepare",
            "--operation", str(operation),
            "--session", str(session),
            "--target-level", str(int(target_level)),
            "--previous-run", str(previous_run),
            "--page-start", str(int(page_start))] + list(extra or [])


def invoke_native_card(*, operation: str, previous_run: str, page_start: int,
                       session: str, target_level: int,
                       execute: bool, intent: str,
                       extra: list[str] | None = None,
                       prepared: dict | None = None,
                       queue: str | None = None) -> dict:
    """⑥ **真实执行器**：prepare → 核 prepared 身份 → dispatch → 独立 decode。

    **GAP-3 修正**：旧实现只跑了一次 `prepare` 就回报 `drivesActualExecution=True`，
    与「实际 prepare/dispatch/decode」的声明不符。现在三步都走 `run_cmd`：
    调用前写 intent、结束后写完整 stdout/stderr/returncode；任一步非零 / 非 JSON /
    `ok` 非 True 即停，**未知不重放**。结构参考 root 已完成
    `tools/playtest-sequence/gameplay.py` 的固定三步。

    `execute=False` 时只核 argv 与输入，**明确回报未真跑**，不得声称已执行。
    """
    cli = [sys.executable, "-B", str(REPO / PLAYTEST_CLI)]
    steps: list[dict] = []

    # ---- step 1: prepare（唯一 run）----
    argv_prepare = native_card_argv(operation=operation, previous_run=previous_run,
                                    page_start=page_start, session=session,
                                    target_level=target_level, extra=extra)
    rec = run_cmd(argv_prepare, execute=execute, intent=f"{intent}:prepare")
    steps.append({"stage": "prepare", "argv": argv_prepare,
                  "journal": rec.get("journal")})
    parsed = rec.get("parsed") or {}
    run_dir = parsed.get("run") or parsed.get("runDir")

    # ---- 核 prepared 身份（kind / session / targetLevel / ancestor）----
    prepared_doc = prepared if isinstance(prepared, dict) else None
    identity_problems: list[str] = []
    prepared_kind_verified = False
    if prepared_doc is not None:
        prepared_kind_verified = prepared_doc.get("kind") == "playtest-control-prepared-v9"
        if not prepared_kind_verified:
            identity_problems.append(f"kind={prepared_doc.get('kind')!r}")
        if session and prepared_doc.get("session") not in (None, session):
            identity_problems.append(f"session={prepared_doc.get('session')!r}")
        if target_level and prepared_doc.get("targetLevelId") not in (None, target_level):
            identity_problems.append(
                f"targetLevelId={prepared_doc.get('targetLevelId')!r}")
    if identity_problems:
        raise EntryError(
            "NATIVE_CARD_PREPARED_MISMATCH",
            f"{intent}: prepared 身份与请求不符（{prepared_doc.get('kind')!r} 应当是 "
            f"playtest-control-prepared-v9）：{'；'.join(identity_problems[:4])}")

    out: dict = {"argv": argv_prepare, "operation": operation,
                 "pageStart": page_start, "executed": rec.get("executed"),
                 "runDir": run_dir, "steps": steps,
                 "preparedKindVerified": prepared_kind_verified,
                 "preparedKind": (prepared_doc or {}).get("kind")}

    if not execute:
        out.update({"drivesActualExecution": False,
                    "note": "execute=False ⇒ 只核 argv 与输入；**未**真正 "
                            "prepare/dispatch/decode，不得据此声称已执行"})
        return out

    if not run_dir:
        raise EntryError("NATIVE_CARD_NO_RUN_DIR",
                         f"{intent}: prepare 未返回 run 目录，无法 dispatch/decode")

    # ---- step 2: dispatch ----
    argv_dispatch = cli + ["dispatch", "--run", str(run_dir)]
    if queue:
        argv_dispatch += ["--elevated-queue", str(queue)]
    rec2 = run_cmd(argv_dispatch, execute=True, intent=f"{intent}:dispatch")
    steps.append({"stage": "dispatch", "argv": argv_dispatch,
                  "journal": rec2.get("journal")})

    # ---- step 3: 独立 decode（原件 SHA 由 journal 保留）----
    argv_decode = cli + ["decode", "--run", str(run_dir)]
    rec3 = run_cmd(argv_decode, execute=True, intent=f"{intent}:decode")
    steps.append({"stage": "decode", "argv": argv_decode,
                  "journal": rec3.get("journal")})

    out.update({"drivesActualExecution": True,
                "dispatchParsed": rec2.get("parsed"),
                "decoded": rec3.get("parsed"),
                "originalReceiptShaPreservedInJournal": True})
    return out


def native_card_reader(*, session: str, target_level: int, previous_run: str,
                       execute: bool, prepared: dict | None = None,
                       queue: str | None = None):
    """把 `invoke_native_card` 变成 contact 分页的**真实读取器**。

    **本轮收口要点**：`invoke_native_card` 之前**只有 def、没有任何调用点** ——
    属于「无人调用的 helper 不算实现完成」。本函数是它的**生产调用者**：
    `assert_dual_source_identity(..., driver={...})` 会用它填
    `contact_side(read_page=...)`，最终由 `main --dual-acceptance` 触达；
    每一页都是一次独立的 prepare → 核身份 → dispatch → 独立 decode。

    `execute=False` 时驱动不真跑：**直接具名拒**，不得把空读数当数据。
    """
    def read_page(i: int, start: int, card: dict) -> dict:
        res = invoke_native_card(
            operation=card.get("operation") or "trial-entities",
            previous_run=previous_run, page_start=int(start),
            session=session, target_level=int(target_level),
            execute=execute, intent=f"contact:page{i}",
            prepared=prepared, queue=queue)
        if not execute:
            raise EntryError(
                "NATIVE_CARD_DRIVER_NOT_EXECUTING",
                f"contact:page{i}: execute=False ⇒ 原生卡驱动未真跑，"
                "不得把空读数当数据（先给 --execute 与真实 session/level/previous-run）")
        decoded = res.get("decoded") or {}
        if not decoded:
            raise EntryError(
                "NATIVE_CARD_DECODE_EMPTY",
                f"contact:page{i}: decode 无输出 ⇒ 不得当作空页通过")
        return decoded
    read_page.__name__ = "native_card_reader"
    read_page.drivesActualExecution = bool(execute)
    return read_page


def assert_v9_consumer(decoded: dict, where: str,
                       *, prepared: dict | None = None) -> dict:
    """⑤ **v9 消费者**（`trial-entities`：prepared-v9 / nativeVersion 8 / op18）。

    普通 row 必须带 `sourceInstance` 与 `targetLevelSpawnMembershipVerified`；
    `belongsToBoundTrial` **只对唯一 GUID 为 true**，**top-level bool 不能代替
    目标逐一选择**。**v8 `contact-state` 的这些字段一律 unknown，不得伪造过门**。
    """
    # **GAP-1 修正（真实 decoder 层次）**：`directory_receipt.py` 真实返回
    # `nativeReceipt.version == 8`、`nativeReceipt.operation == 18`；
    # **顶层没有任何 `nativeVersion` / `preparedVersion` 字段**。
    # 旧写法硬要求顶层这两项 ⇒ 真实回执必拒。改为从 `decoded.nativeReceipt` 读。
    nr = decoded.get("nativeReceipt") or {}
    problems = []
    if decoded.get("operation") != TRIAL_ENTITIES_OP:
        problems.append(f"operation={decoded.get('operation')!r}")
    if nr.get("version") != 8:
        problems.append(f"nativeReceipt.version={nr.get('version')!r}")
    if nr.get("operation") != 18:
        problems.append(f"nativeReceipt.operation={nr.get('operation')!r}")
    if problems:
        raise EntryError("V9_CONSUMER_REQUIRED",
                         f"{where}: 不是 v9 trial-entities 回执：{'；'.join(problems[:3])}"
                         "（v8 contact-state 不得顶替）")
    # **prepared 原件层次**：`manifest prepared.json` 的 kind 必须是
    # `playtest-control-prepared-v9`。它在**独立的 prepared 文档**里，不在回执顶层。
    prepared_kind = (prepared or {}).get("kind") if isinstance(prepared, dict) else None
    prepared_kind_verified = prepared_kind == "playtest-control-prepared-v9"
    if prepared is not None and not prepared_kind_verified:
        raise EntryError("V9_PREPARED_KIND",
                         f"{where}: prepared.kind={prepared_kind!r} != "
                         "playtest-control-prepared-v9")
    rows = [e for e in (decoded.get("entities") or []) if not e.get("localAvatar")]
    # **r32：按 `directory_contract.py:42/50` 的真实字段名核对**
    #   rows 实际带：`targetLevelSpawnMembershipVerified`、`sourceDirectoryIndex`、`sourceInstance`
    #   顶层实际带：`sourceDirectoryKnown`、`sourceDirectory`
    needs_row = ("targetLevelSpawnMembershipVerified", "sourceDirectoryIndex",
                "sourceInstance")
    lacking = [int(e.get("runtimeId")) for e in rows
               if any(k not in e for k in needs_row)]
    if lacking:
        raise EntryError("V9_FIELDS_MISSING",
                         f"{where}: 普通 row 缺 v9 字段 {needs_row}：{lacking[:5]}")
    # `directory_contract.py:50` 顶层必带
    if "sourceDirectoryKnown" not in decoded or "sourceDirectory" not in decoded:
        raise EntryError("V9_FIELDS_MISSING",
                         f"{where}: 缺顶层 `sourceDirectoryKnown`/`sourceDirectory`"
                         "（directory_contract.py:50）")
    # **② 目录侧祖先绑定等式 + enumerator（r33）**
    # `directory_contract.py:33-34` 的真实判据：
    #   `s['global']==state['global'] and s['levelData']==state['data']==state['cache']
    #    and s['editData']==state['cacheEditData']` ⇒ DIRECTORY_TRIAL_SOURCE_BINDING
    #   `s['enumerator']==o['moduleBase']+0x1713e080` ⇒ DIRECTORY_ENUMERATOR
    sd = decoded.get("sourceDirectory") or {}
    # **GAP-2 修正**：`contact/control/after` 与 `moduleBase` 真实都在
    # `decoded.nativeReceipt` 下；`sourceDirectory` 才是顶层。
    # 旧写法读 `decoded.contact` / `decoded.moduleBase` ⇒ 真实回执必缺。
    ctrl = nr.get("contact") or {}
    state = ((ctrl.get("control") or {}).get("after") or {})
    if sd and state:
        binding_ok = (sd.get("global") == state.get("global")
                      and sd.get("levelData") == state.get("data") == state.get("cache")
                      and sd.get("editData") == state.get("cacheEditData"))
        if not binding_ok:
            raise EntryError(
                "DIRECTORY_TRIAL_SOURCE_BINDING",
                f"{where}: 目录侧与 contact 控制流**不是同一祖先 trial/cache**；"
                f"sourceDirectory.global={sd.get('global')!r} "
                f"state.global={state.get('global')!r}；"
                f"levelData/data/cache={sd.get('levelData')!r}/"
                f"{state.get('data')!r}/{state.get('cache')!r}；"
                f"editData/cacheEditData={sd.get('editData')!r}/"
                f"{state.get('cacheEditData')!r}")
        enumerator = sd.get("enumerator")
        module_base = sd.get("moduleBase", nr.get("moduleBase"))
        # **r34**：`moduleBase` 与 `enumerator` 都是必需字段 ——
        # 「无法核 = 不得通过」。缺 `moduleBase` 时**不再跳过**校验（旧写法是
        # `if module_base is not None and ...`，那等于静默放行）。
        missing_enum = [n for n, v in (("moduleBase", module_base),
                                       ("enumerator", enumerator))
                        if v is None]
        if missing_enum:
            raise EntryError(
                "V9_FIELDS_MISSING",
                f"{where}: 缺必需字段 {missing_enum} ⇒ **无法核 DIRECTORY_ENUMERATOR，"
                "不得通过**（与缺 contact.control.after/sourceDirectory 同级）")
        if enumerator != int(module_base) + 0x1713e080:
            raise EntryError(
                "DIRECTORY_ENUMERATOR",
                f"{where}: enumerator={enumerator!r} != moduleBase+0x1713e080 "
                f"({int(module_base) + 0x1713e080:#x})")
        dir_ok = True
    else:
        # 没读到目录侧/控制流 ⇒ **无法证明**，不得当作通过
        dir_ok = False
        raise EntryError("V9_FIELDS_MISSING",
                         f"{where}: 缺 `sourceDirectory` 或 `contact.control.after`"
                         " ⇒ 无法核 `DIRECTORY_TRIAL_SOURCE_BINDING`")
    return {"operation": TRIAL_ENTITIES_OP,
            "nativeReceiptVersion": nr.get("version"),
            "nativeReceiptOperation": nr.get("operation"),
            "preparedKindVerified": prepared_kind_verified,
            "preparedKind": prepared_kind,
            "operationId": decoded.get("operationId"), "rowCount": len(rows),
            "rowFieldsVerified": list(needs_row),
            "sourceDirectoryKnown": decoded.get("sourceDirectoryKnown"),
            "sourceDirectoryCapacity": 8192,
            "directoryTrialSourceBinding": dir_ok,
            "directoryEnumeratorVerified": True,
            "sourceInstancePresent": True,
            "topBoolDoesNotReplacePerTarget": True,
            "v8ContactStateFieldsAreUnknown": True,
            "fieldSource": "tools/playtest-control/directory_contract.py:33-34/42/50；"
                           "DIRECTORY-NATIVE.md:19"}


def reject_v8_fields_as_v9(decoded: dict, where: str) -> dict:
    """⑤ **v8 `contact-state` 保持 ordinary-unknown**：伪造 v9 专属字段即拒。

    **GAP-5 修正**：旧 spoof 列表含顶层 `nativeVersion` / `preparedVersion` ——
    但真实 decoder **从不产生这两个顶层字段**（v9 的真实版本在
    `nativeReceipt.version` / `nativeReceipt.operation`，prepared kind 在独立的
    prepared 文档里）。检查这两个"凭空字段"等于检查一个不存在的面。
    改为检查**真实可被伪造的 v9 专属面**：
      * 顶层 `sourceInstance` / `sourceDirectoryIndex` / `sourceDirectory`
      * `nativeReceipt`（v8 contact-state 不该有原生目录回执）
      * 逐行 `targetLevelSpawnMembershipVerified`
    """
    if decoded.get("operation") == "contact-state":
        spoofed: list[str] = [
            k for k in ("sourceInstance", "sourceDirectoryIndex", "sourceDirectory",
                        "nativeReceipt")
            if decoded.get(k) is not None
        ]
        rows = [e for e in (decoded.get("entities") or [])
                if isinstance(e, dict) and not e.get("localAvatar")]
        if any("targetLevelSpawnMembershipVerified" in e for e in rows):
            spoofed.append("rows[].targetLevelSpawnMembershipVerified")
        if spoofed:
            raise EntryError("V8_FIELDS_SPOOFED_AS_V9",
                             f"{where}: v8 contact-state 出现 v9 专属字段 {spoofed}"
                             " ⇒ **拒绝**（v8 保持 unknown）")
    return {"v8StaysUnknown": True, "spoofedFields": [],
            "checkedFields": ["sourceInstance", "sourceDirectoryIndex",
                              "sourceDirectory", "nativeReceipt",
                              "rows[].targetLevelSpawnMembershipVerified"],
            "removedMeaninglessChecks": ["top-level nativeVersion",
                                         "top-level preparedVersion"]}


# ---------------------------------------------------------------- 执行层
class RunAbort(RuntimeError):
    """**失败即停**：携完整 stdout/stderr/intent 与 journal 路径，不自动重放。"""


JOURNAL_ROOT = REPO / ".runtime-verify/combat-production-journal"

#: 当前**操作级**目录（由执行入口 `set_current_operation` 设置一次）。
#: 旧实现用「全局 JOURNAL_DIR + 每进程 `_seq` 从 0 起」，第二个进程会覆盖
#: 上一次的同名回执；现在所有 `run_cmd` 都落在同一个显式 operation 目录下。
_CURRENT_OP: dict = {"dir": None, "step": 0}


def set_current_operation(op_dir) -> None:
    _CURRENT_OP["dir"] = Path(op_dir) if op_dir is not None else None
    _CURRENT_OP["step"] = 0


def current_operation():
    return _CURRENT_OP["dir"]


def _next_step() -> int:
    _CURRENT_OP["step"] += 1
    return _CURRENT_OP["step"]


def _fsync_write(path: Path, payload: dict, *, exclusive: bool) -> Path:
    """**持久写**：`exclusive=True` 用 `"x"` 模式（已存在即失败），写完 `fsync`。

    旧实现用 `write_text`（`"w"`）⇒ **会覆盖**上一次进程的同名回执，
    等于把「未知/成功」的历史证据抹掉。这里改成独占 + 落盘同步。
    """
    import os as _os
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    mode = "x" if exclusive else "w"
    try:
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            _os.fsync(fh.fileno())
    except FileExistsError:
        raise EntryError(
            "JOURNAL_EXCLUSIVE_VIOLATION",
            f"独占写失败：{path} 已存在 ⇒ 拒绝覆盖既有回执（如需继续请读回定位）")
    return path


def open_operation(operation_id: str | None, *, argv: list[str] | None = None) -> Path:
    """**操作级独占目录**：显式 operation-id，已存在即拒（不自动换 uuid 重建）。

    旧实现是「全局 JOURNAL_DIR + 每进程 `_seq` 从 0 起 + `write_text`」 ——
    第二个进程会把 `001-*.json` 覆盖掉，所谓「独占 intent」并不独占。
    """
    import re as _re
    if not isinstance(operation_id, str) or not _re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", operation_id or ""):
        raise EntryError(
            "JOURNAL_OPERATION_ID_REQUIRED",
            "执行前必须显式给 operation-id（[A-Za-z0-9][A-Za-z0-9._-]{0,95}）；"
            "**不接受自动换 uuid 重建**替已有操作")
    op_dir = JOURNAL_ROOT / operation_id
    try:
        op_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise EntryError(
            "OPERATION_ALREADY_EXISTS",
            f"操作 {operation_id!r} 的目录已存在 ⇒ **拒绝重放**；"
            f"已有回执可读回定位：{op_dir}（不得自动换 uuid 重建）")
    _fsync_write(op_dir / "000-operation-intent.json", {
        "operationId": operation_id,
        "startedUtc": datetime.now(timezone.utc).isoformat(),
        "argv": argv or [],
        "state": "INTENT",
        "replayAllowed": False,
        "outcomeUnknown": False,
        "note": "本目录由 x 模式独占创建；同一 operation-id 不可重放",
    }, exclusive=True)
    return op_dir


def close_operation(op_dir, *, state: str, payload: dict | None = None) -> Path:
    """**写操作最终状态**（COMPLETED / FAILED / UNKNOWN），持久且可定位。

    失败/未知也必须有最终状态文件，否则事后无法判断这次操作究竟停在哪。
    """
    if op_dir is None:
        raise EntryError("JOURNAL_OPERATION_DIR_REQUIRED",
                         "close_operation 需要操作级目录")
    doc = {"operationId": Path(op_dir).name,
           "state": state,
           "finishedUtc": datetime.now(timezone.utc).isoformat(),
           "replayAllowed": False,
           "outcomeUnknown": state == "UNKNOWN",
           **(payload or {})}
    return _fsync_write(Path(op_dir) / "999-operation-final.json", doc, exclusive=True)


def run_cmd(argv: list[str], *, execute: bool, intent: str,
            op_dir: Path | None = None, step: int | None = None) -> dict:
    """**执行层 + 操作级持久 journal**。

    * **调用前**写**独占** intent（`x` 模式 + `fsync`），落在 `<op_dir>/<NNN>-<intent>-intent.json`；
    * **结束后**写**逐步**回执（完整 stdout/stderr/exit）；
    * `returncode != 0` / JSON 非 dict / `ok` 不是 True ⇒ **立即 `RunAbort`**，不继续、不重放；
    * **timeout** ⇒ 保留 `exc.stdout` / `exc.stderr` **原件**，状态标 **`UNKNOWN`**
      （不把超时当失败也不当成功），并 `outcomeUnknown=True`；
    * `execute=True` 而**无 `op_dir`** ⇒ 具名拒（不允许无操作归属的执行）。
    """
    if execute and op_dir is None:
        op_dir = _CURRENT_OP["dir"]
    if execute and op_dir is None:
        raise EntryError(
            "JOURNAL_OPERATION_DIR_REQUIRED",
            f"{intent}: execute 必须绑定操作级目录（先 open_operation(operation_id)）")
    seq = step if step is not None else _next_step()
    stem = f"{seq:03d}-{intent.replace(':', '-').replace('/', '-')}"
    if op_dir is not None:
        pre = _fsync_write(Path(op_dir) / f"{stem}-intent.json", {
            "intent": intent, "argv": argv, "executed": False,
            "state": "INTENT", "recordedUtc": datetime.now(timezone.utc).isoformat(),
            "replayAllowed": False,
        }, exclusive=True)
    else:
        # 纯 dry-run（execute=False 且无 op_dir）：不落操作目录，只在内存返回
        pre = None
    if not execute:
        return {"executed": False, "argv": argv, "intent": intent,
                "journal": str(pre) if pre else None}

    def _write_unknown(payload_extra: dict) -> Path | None:
        if op_dir is None:
            return None
        return _fsync_write(Path(op_dir) / f"{stem}-unknown.json", {
            "intent": intent, "argv": argv,
            "state": "UNKNOWN", "outcomeUnknown": True, "replayAllowed": False,
            **payload_extra}, exclusive=True)

    def _raw_record(raw) -> dict:
        """**逐字节原件**：原始 bytes 用 base64 保存；文本只是可读副本。

        `errors="replace"` 解码会**毁掉乱码证据**，所以不能只存解码文本 ——
        原 bytes（base64）才是证据，文本标注 `textMayBeLossy` 仅作阅读。
        """
        import base64 as _b64
        if raw is None:
            return {"present": False, "bytesBase64": None, "bytesLen": 0,
                    "textUtf8": None, "textMayBeLossy": False,
                    "note": "无输出（未捕获到任何字节）"}
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
        try:
            text = raw.decode("utf-8")
            lossy = False
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            lossy = True
        return {"present": True,
                "bytesBase64": _b64.b64encode(raw).decode("ascii"),
                "bytesLen": len(raw), "textUtf8": text,
                "textMayBeLossy": lossy,
                "note": "**逐字节原件在 bytesBase64**；textUtf8 仅是可能失真的可读副本"}

    try:
        # **不用 text=True**：这样拿到的才是原始 bytes，可做逐字节保全。
        p = subprocess.run(argv, cwd=str(REPO), capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        unk = _write_unknown({
            "reason": "TIMEOUT",
            "timeout": exc.timeout,
            "stdoutRaw": _raw_record(exc.stdout),
            "stderrRaw": _raw_record(exc.stderr),
        })
        raise RunAbort(
            f"{intent}: 超时 {exc.timeout}s ⇒ **状态 UNKNOWN**"
            f"（既非成功也非确定失败）；逐字节原件已存 journal={unk}；不重放") from None
    out_raw = p.stdout if isinstance(p.stdout, bytes) else (p.stdout or b"")
    err_raw = p.stderr if isinstance(p.stderr, bytes) else (p.stderr or b"")
    out_rec, err_rec = _raw_record(out_raw), _raw_record(err_raw)
    out, err = out_rec["textUtf8"] or "", err_rec["textUtf8"] or ""
    if op_dir is not None:
        post = _fsync_write(Path(op_dir) / f"{stem}-result.json", {
            "intent": intent, "argv": argv, "returncode": p.returncode,
            "stdoutFull": out, "stderrFull": err,
            "stdoutRaw": out_rec, "stderrRaw": err_rec,
            "state": "RESULT", "replayAllowed": False}, exclusive=True)
    else:
        post = None
    if p.returncode != 0:
        unk = _write_unknown({"reason": "NONZERO_EXIT", "returncode": p.returncode,
                              "stdoutFull": out, "stderrFull": err})
        raise RunAbort(f"{intent}: returncode={p.returncode}; argv={' '.join(argv)}; "
                       f"journal={post or pre or unk}（**失败即停，不重放**）")
    # **非 dict / ok 不是 True / 无法判定 ⇒ 立即停**
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        unk = _write_unknown({"reason": "NON_JSON_OUTPUT",
                              "stdoutFull": out, "stderrFull": err})
        raise RunAbort(f"{intent}: 输出不是 JSON ⇒ **无法判定**，立即停；"
                       f"journal={unk}（不重放）") from None
    if not isinstance(doc, dict):
        unk = _write_unknown({"reason": "JSON_NOT_DICT", "stdoutFull": out})
        raise RunAbort(f"{intent}: 输出 JSON 不是 dict ⇒ 无法判定；journal={unk}")
    if doc.get("ok") is not True:
        unk = _write_unknown({"reason": "BUSINESS_OK_NOT_TRUE",
                              "businessOk": doc.get("ok"), "businessCode": doc.get("code"),
                              "stdoutFull": out, "stderrFull": err})
        raise RunAbort(f"{intent}: 业务 ok={doc.get('ok')!r} != True; "
                       f"code={doc.get('code')}; journal={unk}（**失败即停，不重放**）")
    return {"executed": True, "intent": intent, "argv": argv,
            "returncode": p.returncode, "stdoutFull": out, "stderrFull": err,
            "parsed": doc, "journal": str(post) if post else None,
            "intentJournal": str(pre) if pre else None, "replayAllowed": False}


def resolve_entity_id_from_receipt(rec: dict, ref: str) -> int:
    """**逐实体**：从该次 create 的**自己的回执**取精确 `entityId`（缺陷 2 的正解）。

    `scene_cli.py:555` 的创建返回带 `entityId` / `run` / `receipt`。
    **不做「创建 6 个后全量差分排序 zip」**。
    """
    doc = rec.get("parsed") or {}
    eid = doc.get("entityId")
    if not isinstance(eid, int) or isinstance(eid, bool):
        raise EntryError("NATIVE_ID_RECEIPT_MISSING",
                         f"{ref}: create 回执里没有整数 entityId（journal={rec.get('journal')}）")
    return eid


def require_fresh_reviews(ctx: dict, refs: list[str]) -> dict:
    """**每次 create 一个精确 review**（缺陷 5）。

    原审查绑定**精确请求 + 当前 baseline**，**不能重复用于不同实体**。
    """
    reviews = ctx.get("reviews") or {}
    missing = [r for r in refs if not reviews.get(r)]
    if missing:
        raise EntryError("DISPATCH_CONTEXT_MISSING",
                         f"缺这些实体的**独立 review**：{missing}；"
                         "原审查绑定精确请求/当前 baseline，**不得复用同一 review 建多个实体**")
    vals = [str(reviews[r]) for r in refs]
    if len(set(vals)) != len(vals):
        raise EntryError("DISPATCH_CONTEXT_MISSING",
                         "reviews 里有重复路径 ⇒ 同一 review 被复用（禁止）")
    return reviews


def plan_inspect(ctx: dict, tag: str) -> dict:
    """**创建前后都要真 inspect**（缺陷 2）：不靠外部预传的实体表。"""
    return {"tag": tag, "argv": [sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI),
                                 "inspect",
                                 "--session", str(ctx.get("session") or ""),
                                 "--level-id", str(ctx.get("levelId") or ""),
                                 "--elevated-queue", str(ctx.get("queue") or "")]}


def build_graph_lifecycle(ctx: dict, inst: dict, entity_ids: list[int] | None) -> dict:
    """**真实图生命周期（严格顺序）**：

    `create`（唯一名称）→ `lookup` 取**真 graphId** → `inspect`（空图核验）
    → `build-plan --graph-id` → `inspect`（节点数核验）→ `bind ×N` → `inspect`（`boundEntityIds` 确认）

    依据：`author.py:695-703` 的 `--request-id/--run-id/--name/--graph-id`；
    `AuthoringGraph.cs:185-197` 每 action 字段白名单；
    `:360` create 返回 `create-requested-readback-pending`；
    `:363` lookup 无匹配返回 `lookup-pending`（无 graphId）；
    `:382-386` inspect/lookup 返回 `boundEntityIds` / `boundToLevel`；
    `:451` bind 返回 `binding-requested-readback-pending`（**不是成功**）。
    """
    queue = ctx.get("queue")
    run_id = ctx.get("runId")
    rid = ctx.get("requestId")
    if not queue or not run_id or not rid:
        raise EntryError("DISPATCH_CONTEXT_MISSING",
                         "缺 queue / runId / requestId（**不得留占位**）")
    # `AuthoringGraph.cs:364` 要求 matches.Length==1 ⇒ **名称必须唯一**，总是派生
    name = unique_graph_name(ctx, inst["campRef"])
    camp = inst["campRef"]
    # **全局 --elevated-queue 在 graph 之前**
    base = [sys.executable, "-B", str(REPO / ENTRY_AUTHOR),
            "--elevated-queue", str(queue), "graph"]
    rid_of = lambda act: f"{rid}-{camp}-{act}"          # noqa: E731  每 action 独立
    create = base + ["create", "--request-id", rid_of("create"), "--run-id", run_id,
                     "--name", name, "--graph-kind", str(inst["graphKind"])]
    lookup = base + ["lookup", "--request-id", rid_of("lookup"), "--run-id", run_id,
                     "--name", name]
    inspect0 = base + ["inspect", "--request-id", rid_of("inspect0"), "--run-id", run_id,
                       "--name", name, "--graph-id", "<from-lookup>"]
    build = base + ["build-plan", "--request-id", rid_of("build"), "--run-id", run_id,
                    "--name", name, "--graph-id", "<from-lookup>",
                    "--expected-node-count", "0", "--plan-file", inst["planFile"]]
    inspect1 = base + ["inspect", "--request-id", rid_of("inspect1"), "--run-id", run_id,
                       "--name", name, "--graph-id", "<from-lookup>"]
    inspect2 = base + ["inspect", "--request-id", rid_of("inspect2"), "--run-id", run_id,
                       "--name", name, "--graph-id", "<from-lookup>"]
    return {"create": create, "lookup": lookup, "inspect0": inspect0,
            "build": build, "inspect1": inspect1, "inspect2": inspect2,
            "graphName": name,
            "graphIdPlaceholder": "<from-lookup>",
            "graphIdSource": "graph lookup → backend.graphId（注入后续每一步 --graph-id）",
            "requestIds": {a: rid_of(a) for a in
                           ("create", "lookup", "inspect0", "build", "inspect1",
                            "inspect2")},
            "queueBeforeGraph": True,
            "bindReceiptIsNotSuccess": "**bind 回执恒为 binding-requested-readback-pending**；"
                                       "成功只由 inspect2.boundEntityIds 确认"}


def plan_bind_argv(ctx: dict, inst: dict, graph_id: str, ref: str, entity_id: int,
                   node_count: int) -> list[str]:
    """**真实 bind 入口**（`author.py:775` / `AuthoringGraph.cs:197` / README:127）。

    字段白名单 `bind = {graphId, expectedNodeCount, entityId}` ⇒ 只给这三项 + 全局参数。
    """
    return [sys.executable, "-B", str(REPO / ENTRY_AUTHOR),
            "--elevated-queue", str(ctx["queue"]), "graph", "bind",
            "--run-id", str(ctx["runId"]),
            "--request-id", f"{ctx['requestId']}-{inst['campRef']}-bind-{ref}",
            "--name", unique_graph_name(ctx, inst["campRef"]),
            "--graph-id", str(graph_id),
            "--entity-id", str(entity_id),
            "--expected-node-count", str(int(node_count))]


#: **execute 的目标关卡**（1843）与**必须拒绝的受保护关卡**（1842）。
TARGET_LEVEL_ID = 1073741843
FORBIDDEN_LEVEL_IDS = {1073741842}


def _read_json_file(path) -> dict | None:
    try:
        p = Path(str(path))
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return None


_LEVEL_KEYS = ("levelId", "level_id", "targetLevelId", "targetLevel", "LevelId")


def _level_of(doc) -> int | None:
    """从真实文档里取关卡号（浅层键）。取不到返回 None，**不猜**。"""
    if not isinstance(doc, dict):
        return None
    for k in _LEVEL_KEYS:
        v = doc.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            return int(v)
    return None


def _SUPERSEDED_level_from_json_files_NOT_CALLED(ctx: dict) -> dict:
    """**已被取代、不再被调用**（保留仅为审计历史）。

    旧方案从"任意 JSON 同填 levelId"取事实 —— 那只是把 CLI 数字换到文件里，
    **不构成原生身份事实**，且真实 session 未必含 levelId。
    现行实现见 `fresh_readonly_native_identity`：走既有
    `scene_cli inspect --large-scene` → `build_readonly_profile.py decode` 真实链，
    用 `levelObservation.verified/levelId` 与 `build-result.json` 的 targetPid/TargetTid。
    """
    facts: dict[str, int] = {}
    missing: list[str] = []

    # 1) 真实 session 文件
    sess_path = ctx.get("sessionFile") or ctx.get("session_file") or ctx.get("session")
    sess_doc = _read_json_file(sess_path) if sess_path else None
    lv = _level_of(sess_doc)
    if lv is None:
        missing.append(f"session_file({sess_path})")
    else:
        facts["sessionFile"] = lv

    # 2) fresh scene inspect 严格 readback
    insp = ctx.get("inspectRunDir")
    insp_doc = None
    if insp:
        d = Path(str(insp))
        for name in ("result.json", "stdout.jsonl"):
            insp_doc = _read_json_file(d / name)
            if insp_doc is not None:
                break
    lv = _level_of(insp_doc)
    if lv is None:
        missing.append(f"inspectReadback({insp})")
    else:
        facts["inspectReadback"] = lv

    # 3) bridge run 资料
    br = _read_json_file(ctx.get("bridgeRunInfo")) if ctx.get("bridgeRunInfo") else None
    lv = _level_of(br)
    if lv is None:
        missing.append(f"bridgeRunInfo({ctx.get('bridgeRunInfo')})")
    else:
        facts["bridgeRunInfo"] = lv

    # 4) 当前 PID 关卡
    pid = _read_json_file(ctx.get("pidLevelFile")) if ctx.get("pidLevelFile") else None
    lv = _level_of(pid)
    if lv is None:
        missing.append(f"pidLevel({ctx.get('pidLevelFile')})")
    else:
        facts["pidLevel"] = lv

    if missing:
        raise EntryError(
            "LEVEL_AUTHENTICITY_INCOMPLETE",
            f"关卡身份必须来自原生事实，但缺 {missing} ⇒ **缺真实性即停**"
            "（CLI 三次同填 1843 不构成身份事实；需真实 session 文件 / fresh inspect "
            "readback / bridge run 资料 / 当前 PID 关卡）")

    distinct = sorted(set(facts.values()))
    if len(distinct) != 1:
        raise EntryError(
            "LEVEL_AUTHENTICITY_CONFLICT",
            f"关卡来源互相不一致：{facts} ⇒ 拒绝执行")
    authentic = distinct[0]

    # **交叉核对** CLI 传值（不是事实来源）
    cli_lvl = ctx.get("levelId")
    if cli_lvl is None:
        raise EntryError("LEVEL_NOT_SPECIFIED", "execute 必须显式提供 levelId（作交叉核对）")
    if int(cli_lvl) != authentic:
        raise EntryError(
            "LEVEL_CLI_VS_NATIVE_MISMATCH",
            f"CLI --level-id={cli_lvl} 与原生事实 {authentic} 不符 ⇒ 拒绝")
    if authentic in FORBIDDEN_LEVEL_IDS:
        raise EntryError(
            "LEVEL_1842_FORBIDDEN",
            f"原生事实关卡={authentic} 属于受保护 1842 ⇒ **拒绝执行**（保护 1842）")
    if authentic != TARGET_LEVEL_ID:
        raise EntryError(
            "LEVEL_NOT_TARGET_1843",
            f"原生事实关卡={authentic} != execute 目标 {TARGET_LEVEL_ID} ⇒ 拒绝")
    return {"authenticLevelId": authentic, "factsBySource": facts,
            "sourcesRequired": 4,
            "cliValueIsCrossCheckOnly": True,
            "target": TARGET_LEVEL_ID,
            "forbiddenRejected": sorted(FORBIDDEN_LEVEL_IDS)}


#: .NET `DateTime.Ticks` 起点(0001-01-01)与 FILETIME 起点(1601-01-01)相差的 100ns 区间数。
#: **两个纪元不能直接比**，必须先归一化。
_TICKS_0001_MINUS_1601 = 504911232000000000

#: scope 中属于**敏感**字段，不得输出/落盘
_SCOPE_SECRET_FIELDS = ("nonce", "pipeName")


def _ticks_to_filetime(ticks: int) -> int:
    """把 .NET ticks(0001 纪元) 转成 FILETIME(1601 纪元) 的 100ns 计数。

    `new-scope.py` 的 `startUtcTicks` 来自 `process_start_utc_ticks`（.NET ticks）；
    而 `session['processCreation']` 是 FILETIME 口径。**直接比较会把两者混为一谈**。
    """
    return int(ticks) - _TICKS_0001_MINUS_1601


def _same_image(a, b) -> bool:
    if not a or not b:
        return False
    try:
        return str(Path(str(a)).resolve()).lower() == str(Path(str(b)).resolve()).lower()
    except (OSError, ValueError):
        return str(a).lower() == str(b).lower()


def assert_scope_binds_session(scope: dict | None, session: dict | None) -> dict:
    """**同一作用域证据**：scope(pid/startUtcTicks/expectedExe) 必须绑定本次 session。

    scope 契约来自 `tools/editor-bridge/new-scope.py:13`：
    `(pid, startUtcTicks, nonce, pipeName, expiresUtc, expectedExe)`。
    session 身份来自 `build_readonly_profile.py:53-55`：
    `pid / tid / processCreation / threadCreation / image`。

    比较（**注意时间单位**）：
      * `scope.pid` == `session.pid`
      * `_ticks_to_filetime(scope.startUtcTicks)` == `session.processCreation`
      * `scope.expectedExe` 与 `session.image` 同路径
    输出**只含必要身份证据**；`nonce` / `pipeName` **红action后不出现**。
    缺 scope 或 session ⇒ `SCOPE_BINDING_EVIDENCE_MISSING`（**不得先建实体再发现图不属目标**）。
    """
    if not isinstance(scope, dict) or not scope:
        raise EntryError(
            "SCOPE_BINDING_EVIDENCE_MISSING",
            "缺固定 scope 证据（new-scope 产物）⇒ 无同一作用域证据，"
            "**禁止继续创建实体**")
    if not isinstance(session, dict) or not session:
        raise EntryError(
            "SCOPE_BINDING_EVIDENCE_MISSING",
            "缺 session 身份（prepared.json 的 session）⇒ 无法绑定作用域")
    problems: list[str] = []
    s_pid, x_pid = session.get("pid"), scope.get("pid")
    if s_pid is None or x_pid is None or int(s_pid) != int(x_pid):
        problems.append(f"pid scope={x_pid!r} session={s_pid!r}")
    st = scope.get("startUtcTicks")
    pc = session.get("processCreation")
    if st is None or pc is None:
        problems.append(f"startUtcTicks/processCreation 缺失 scope={st!r} session={pc!r}")
    else:
        try:
            if _ticks_to_filetime(int(str(st))) != int(pc):
                problems.append(
                    f"processCreation 不匹配 scope→FILETIME="
                    f"{_ticks_to_filetime(int(str(st)))} session={pc}")
        except (TypeError, ValueError):
            problems.append(f"startUtcTicks={st!r} 不可解析")
    if not _same_image(scope.get("expectedExe"), session.get("image")):
        problems.append(
            f"image scope={scope.get('expectedExe')!r} session={session.get('image')!r}")
    if problems:
        raise EntryError(
            "SCOPE_SESSION_MISMATCH",
            "scope 与 session **不是同一作用域** ⇒ 拒绝（不得先创建再发现图不属目标）；"
            + "；".join(problems[:4]))
    redacted = {k: v for k, v in scope.items() if k not in _SCOPE_SECRET_FIELDS}
    return {"sameScope": True,
            "scopeEvidence": {"pid": x_pid, "startUtcTicks": str(st),
                              "startUtcTicksEpoch": "dotnet-0001",
                              "sessionProcessCreationFiletime": int(pc),
                              "ticksNormalization": "-504911232000000000",
                              "expectedExe": redacted.get("expectedExe"),
                              "expiresUtc": redacted.get("expiresUtc")},
            "sessionEvidence": {"pid": session.get("pid"), "tid": session.get("tid"),
                                "processCreation": pc,
                                "threadCreation": session.get("threadCreation"),
                                "image": session.get("image")},
            "redactedFields": list(_SCOPE_SECRET_FIELDS),
            "secretsLeaked": False}


#: author 桥的真实 run 产物根（`author.py:30` 同源常量）
RUNS_DIR = REPO / ".runtime/editor-bridge/runs"

_SCOPE_SIX_FIELDS = ("pid", "startUtcTicks", "nonce", "pipeName", "expiresUtc", "expectedExe")


def load_author_scope_from_run(run_id: str | None) -> dict:
    """**由 `--run-id` 自动派生 author scope**（不要求用户再手传 --author-scope）。

    真实产物位置（`author.py:30` / `:373-378`）：
    `.runtime/editor-bridge/runs/<run-id>/bridge-settings.json`，其内容就是
    **六字段 scope 契约**（实测键名）：
    `expectedExe, expiresUtc, nonce, pid, pipeName, startUtcTicks`。

    绑定要求：
      * `run_id` 必须是 UUID 形态，且**解析后的路径必须在 `RUNS_DIR` 内**（防穿越）；
      * 文件必须存在，并记录 **path + sha256**（路径/UUID/SHA 三绑）；
      * 六字段必须齐（缺即拒，不用猜）；
      * **未过期**（`expiresUtc > now`）且 **`lease-closed.json` 不存在**
        ——与 `author.py:378` 同一规则。
    返回的 scope 只供内部比对；`nonce`/`pipeName` 由下游红action，不输出。
    """
    import re as _re
    if not isinstance(run_id, str) or not _re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", run_id or ""):
        raise EntryError("AUTHOR_RUN_ID_INVALID",
                         f"--run-id={run_id!r} 不是 UUID 形态 ⇒ 无法定位真实 run 产物")
    run_dir = (RUNS_DIR / run_id).resolve()
    try:
        run_dir.relative_to(RUNS_DIR.resolve())
    except ValueError:
        raise EntryError("AUTHOR_RUN_PATH_ESCAPE",
                         f"run_id={run_id!r} 解析后逃出 RUNS_DIR ⇒ 拒绝") from None
    settings_path = run_dir / "bridge-settings.json"
    if not settings_path.is_file():
        raise EntryError(
            "AUTHOR_RUN_SETTINGS_MISSING",
            f"{settings_path} 不存在 ⇒ 该 run 没有真实 bridge-settings 产物")
    try:
        raw = settings_path.read_bytes()
        scope = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        raise EntryError("AUTHOR_RUN_SETTINGS_UNREADABLE",
                         f"{settings_path} 不可解析") from None
    if not isinstance(scope, dict):
        raise EntryError("AUTHOR_RUN_SETTINGS_UNREADABLE",
                         f"{settings_path} 不是 JSON 对象")
    missing = [f for f in _SCOPE_SIX_FIELDS if f not in scope]
    if missing:
        raise EntryError(
            "AUTHOR_SCOPE_CONTRACT_INCOMPLETE",
            f"bridge-settings 缺六字段 {missing}；实际 keys={sorted(scope)}")
    # 过期 / 已关闭（author.py:378 同一规则）
    exp = scope.get("expiresUtc")
    try:
        exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        not_expired = exp_dt.tzinfo is not None and exp_dt > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        raise EntryError("AUTHOR_SCOPE_EXPIRY_UNPARSABLE",
                         f"expiresUtc={exp!r} 不可解析") from None
    lease_closed = (run_dir / "lease-closed.json").exists()
    if not not_expired:
        raise EntryError("AUTHOR_SCOPE_EXPIRED",
                         f"run {run_id} 的 scope 已过期（expiresUtc={exp}）")
    if lease_closed:
        raise EntryError("AUTHOR_LEASE_CLOSED",
                         f"run {run_id} 的 lease 已关闭（lease-closed.json 存在）")
    import hashlib as _hl
    return {"runId": run_id, "path": str(settings_path),
            "sha256": _hl.sha256(raw).hexdigest(),
            "scope": scope,
            "sixFieldsPresent": list(_SCOPE_SIX_FIELDS),
            "notExpired": True, "leaseClosed": False,
            "leaseVerified": True}


def require_author_scope_binding(ctx: dict, session_identity: dict | None) -> dict:
    """**author graph 调用必须与本次只读 session 同一作用域**。

    为什么不能省：`author.py:373` 的 lease 只校验 `expiresUtc` / `closed`，
    **不校验"本次只读 1843"** ⇒ 光有 lease 不能证明图属于目标作用域。
    因此必须拿到 **new-scope 的真实 scope 产物**（`(pid, startUtcTicks, nonce,
    pipeName, expiresUtc, expectedExe)`）并与 session 身份比对；
    **拿不到 ⇒ `AUTHOR_RUN_SCOPE_UNVERIFIED`，禁止创建实体后才去发现图不属目标**。
    """
    # ---- 作用域来源：execute **默认由 runId 自动派生**；显式覆盖仅离线审阅 ----
    provenance: dict
    explicit = ctx.get("authorScope")
    if isinstance(explicit, dict) and explicit:
        author_scope = explicit
        provenance = {"source": "explicit-override",
                      "note": "仅离线审阅用；execute 正常路径应由 runId 自动派生"}
    else:
        run_id = ctx.get("runId")
        if not run_id:
            raise EntryError(
                "AUTHOR_RUN_SCOPE_UNVERIFIED",
                "既无显式 scope 覆盖也无 --run-id ⇒ 无法按真实 run 产物 "
                "(.runtime/editor-bridge/runs/<run-id>/bridge-settings.json) 派生作用域；"
                "**无同一作用域证据禁止创建实体**")
        loaded = load_author_scope_from_run(run_id)
        author_scope = loaded["scope"]
        provenance = {"source": "derived-from-runId",
                      "runId": loaded["runId"],
                      "path": loaded["path"],
                      "sha256": loaded["sha256"],
                      "sixFieldsPresent": loaded["sixFieldsPresent"],
                      "notExpired": loaded["notExpired"],
                      "leaseClosed": loaded["leaseClosed"]}
    binding = assert_scope_binds_session(author_scope, session_identity)
    return {"authorRunScopeBinding": binding, "verified": True,
            "provenance": provenance,
            "runIdBound": provenance.get("source") == "derived-from-runId",
            "pathUuidShaBound": provenance.get("sha256") is not None,
            "secretsRedacted": True}


def fresh_readonly_native_identity(ctx: dict) -> dict:
    """**execute 内部新鲜取得只读原生身份**（不发明用户前置文件）。

    复用**既有真实链**（`tools/mondstadt/integration/run_delivery.py::_fresh_baseline`
    L285-342 的同一组判据）：

      1. `scene_cli inspect --large-scene --session S --level-id ID --elevated-queue Q`
         ⇒ 回执里必须 `ok is True` / `cleanupVerified is True` / `nativeStarted is True`
         （**精确 is 比较**）、`readonlyAcceptance.ok is True`；
      2. 回执 `run/runDir/output/prepared/saveRun` 给出**真实 run 目录**（不按 mtime 猜）；
      3. `run/exit.json` 与 `run/result.json` 必须存在；
      4. `run/build-result.json` 的 **`targetPid` = session['pid']、`targetTid` = session['tid']**
         （`build_readonly_profile.py:241`）；
      5. **独立 decode**：`build_readonly_profile.py decode --run <run>`
         ⇒ 必须 `ok is True`，且 **`levelObservation.verified is True`**，
         `levelObservation.levelId` 是**原生观测到的关卡**（`:259`/`:291`）。

    随后：原生 `levelId` 与 CLI `--level-id` 交叉核对；**拒 1842**、须 **1843**。
    返回的身份（levelId/targetPid/targetTid/run/profileId）由 execute 后续绑定复用。
    """
    session = ctx.get("session")
    cli_level = ctx.get("levelId")
    queue = ctx.get("queue") or ctx.get("elevatedQueue")
    if not session or cli_level is None or not queue:
        raise EntryError(
            "LEVEL_FRESH_CHAIN_PREREQ_MISSING",
            f"新鲜只读身份需要 --session / --level-id / --elevated-queue，"
            f"实得 session={session!r} levelId={cli_level!r} queue={queue!r}")

    # ---- 1) 真实 scene_cli inspect（既有入口，不新造 schema）----
    argv_inspect = [sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI), "inspect",
                    "--large-scene", "--session", str(session),
                    "--level-id", str(int(cli_level)),
                    "--elevated-queue", str(queue)]
    rec = run_cmd(argv_inspect, execute=True, intent="fresh-baseline:scene-inspect")
    rj = rec.get("parsed") or {}
    if rj.get("ok") is not True or rj.get("cleanupVerified") is not True \
            or rj.get("nativeStarted") is not True:
        raise EntryError(
            "FRESH_BASELINE_INSPECT_INCOMPLETE",
            f"只读 inspect 回执必须 ok/cleanupVerified/nativeStarted 三者均精确 True；"
            f"实得 ok={rj.get('ok')!r} cleanupVerified={rj.get('cleanupVerified')!r} "
            f"nativeStarted={rj.get('nativeStarted')!r}")
    ra = rj.get("readonlyAcceptance") if isinstance(rj.get("readonlyAcceptance"), dict) else {}
    if ra.get("ok") is not True:
        raise EntryError("FRESH_BASELINE_READONLY_NOT_OK",
                         f"readonlyAcceptance.ok={ra.get('ok')!r} ≠ True")

    # ---- 2) 真实 run 目录（不按 mtime 猜）----
    run_dir = None
    for key in ("run", "runDir", "output", "prepared", "saveRun"):
        if rj.get(key):
            run_dir = Path(str(rj[key]))
            break
    if run_dir is None or not run_dir.exists():
        raise EntryError("FRESH_BASELINE_RUN_NOT_IN_RECEIPT",
                         "只读 inspect 回执里没有可识别的 run 目录")
    for name in ("exit.json", "result.json"):
        if not (run_dir / name).is_file():
            raise EntryError("FRESH_BASELINE_RECEIPT_MISSING",
                             f"{run_dir / name} 不存在 ⇒ 不承认该 baseline")

    # ---- 3) build-result.json 的 targetPid/targetTid **与 session 真值比对** ----
    br = _read_json_file(run_dir / "build-result.json") or {}
    target_pid, target_tid = br.get("targetPid"), br.get("targetTid")
    if not isinstance(target_pid, int) or not isinstance(target_tid, int):
        raise EntryError(
            "FRESH_BASELINE_PID_TID_MISSING",
            f"build-result.json 缺 targetPid/targetTid（实得 {br.get('targetPid')!r}/"
            f"{br.get('targetTid')!r}）⇒ 无原生身份")
    # prepared.json 里带真实 session（build_readonly_profile.py:265 用 prepared['session']）
    prepared_doc = _read_json_file(run_dir / "prepared.json") or {}
    session = prepared_doc.get("session") if isinstance(prepared_doc.get("session"), dict) else None
    if session is None:
        raise EntryError(
            "SCOPE_BINDING_EVIDENCE_MISSING",
            f"{run_dir}/prepared.json 里没有 session ⇒ 无法核 pid/tid/creation/image 身份")
    if session.get("pid") != target_pid or session.get("tid") != target_tid:
        raise EntryError(
            "SESSION_PID_TID_MISMATCH",
            f"build-result targetPid/Tid={target_pid}/{target_tid} 与 session "
            f"pid/tid={session.get('pid')}/{session.get('tid')} **不一致** ⇒ 拒（旧版只查 int，等于没查）")

    # ---- 3b) **同一作用域证据**：scope ↔ session（缺则禁止继续创建实体）----
    scope = br.get("scope") if isinstance(br.get("scope"), dict) else None
    if scope is None:
        scope = _read_json_file(run_dir / "scope.json")
    if scope is None:
        scope = prepared_doc.get("scope") if isinstance(prepared_doc.get("scope"), dict) else None
    scope_binding = assert_scope_binds_session(scope, session)

    # ---- 4) 独立 decode（既有 decoder）----
    argv_dec = [sys.executable, "-B", str(REPO / ENTRY_READONLY_PROFILE),
                "decode", "--run", str(run_dir)]
    drec = run_cmd(argv_dec, execute=True, intent="fresh-baseline:decode")
    dj = drec.get("parsed") or {}
    if dj.get("ok") is not True:
        raise EntryError("FRESH_BASELINE_DECODE_NOT_OK",
                         f"独立 decode 未 ok ⇒ 原始验收不成立；实得 {dj.get('ok')!r}")
    lo = dj.get("levelObservation") if isinstance(dj.get("levelObservation"), dict) else {}
    if lo.get("verified") is not True:
        raise EntryError("LEVEL_NOT_OBSERVED",
                         f"decode.levelObservation.verified={lo.get('verified')!r} ≠ True "
                         "⇒ 关卡未被原生观测到，不得当事实")
    native_level = lo.get("levelId")
    if not isinstance(native_level, int):
        raise EntryError("LEVEL_NOT_OBSERVED",
                         f"decode.levelObservation.levelId={native_level!r} 不是整数")

    # ---- 5) 交叉核对 + 1842 / 1843 ----
    if int(cli_level) != int(native_level):
        raise EntryError(
            "LEVEL_CLI_VS_NATIVE_MISMATCH",
            f"CLI --level-id={cli_level} 与原生观测 {native_level} 不符 ⇒ 拒绝")
    if int(native_level) in FORBIDDEN_LEVEL_IDS:
        raise EntryError("LEVEL_1842_FORBIDDEN",
                         f"原生关卡={native_level} 属受保护 1842 ⇒ 拒绝执行")
    if int(native_level) != TARGET_LEVEL_ID:
        raise EntryError("LEVEL_NOT_TARGET_1843",
                         f"原生关卡={native_level} != 目标 {TARGET_LEVEL_ID}")
    return {"levelId": int(native_level),
            "cliValueIsCrossCheckOnly": True,
            "targetPid": target_pid, "targetTid": target_tid,
            "runDir": str(run_dir),
            "profileId": br.get("profileId"),
            "entityCount": dj.get("entityCount"),
            "levelObservation": lo,
            "readonlyAcceptance": ra,
            "scopeBinding": scope_binding,
            "sessionIdentity": scope_binding.get("sessionEvidence"),
            "source": "scene_cli inspect --large-scene → build_readonly_profile decode",
            "freshlyObtainedInsideExecute": True}


def assert_execute_level(ctx: dict) -> dict:
    """execute 关卡守卫：**调用既有真实只读链新鲜取得原生身份**。"""
    return fresh_readonly_native_identity(ctx)


def run_entry(*, ground_path: str | None, semantic_ids_path: str | None,
              ctx: dict, execute: bool, entity_before: dict | None,
              entity_after: dict | None) -> dict:
    candidate = read_json(CANDIDATE)
    # **semanticIds 回执来源**：路径 + SHA256 一起带进 provenance，
    # 便于事后复核「这个 currency ID 到底出自哪份回执」。
    semantic_ids = read_json(semantic_ids_path) if semantic_ids_path else None
    semantic_receipt_prov: dict = {"path": None, "sha256": None,
                                   "operation": None, "sessionSha256": None}
    if semantic_ids_path:
        import hashlib as _hl
        _p = Path(semantic_ids_path)
        semantic_receipt_prov["path"] = str(_p)
        if _p.is_file():
            semantic_receipt_prov["sha256"] = _hl.sha256(_p.read_bytes()).hexdigest()
        # **operation.json 证据**：真实回执的 `run` 就是 operation 目录，
        # 其下 operation.json 的 inputs 是 {文件绝对路径: sha256}（含 session）。
        _op_run = (semantic_ids or {}).get("run")
        if _op_run:
            _op_json = Path(str(_op_run)) / "operation.json"
            if _op_json.is_file():
                semantic_receipt_prov["operation"] = read_json(str(_op_json))
    # **session 原始文件指纹**：用于核 operation.json.inputs 里的 session sha256。
    # 真实回执没有顶层 session 字段 ⇒ 必须从原 source 读、算指纹核对。
    # **不得因文件不存在就默默不传**：那样会绕开身份校验。
    for _sk in ("sessionFile", "session_file", "session"):
        _sv = (ctx or {}).get(_sk)
        if not _sv:
            continue
        _sp = Path(str(_sv))
        if _sp.is_file():
            import hashlib as _hl2
            semantic_receipt_prov["sessionFile"] = str(_sp)
            semantic_receipt_prov["sessionSha256"] = _hl2.sha256(
                _sp.read_bytes()).hexdigest()
        else:
            semantic_receipt_prov["sessionMissingPath"] = str(_sv)
        break
    # **execute 必须拒**：session 文件不存在就无从核身份，不能继续执行。
    if execute and semantic_receipt_prov.get("sessionMissingPath"):
        raise EntryError(
            "SESSION_FILE_MISSING_FOR_EXECUTE",
            f"execute 要求 session 文件可读，但 {semantic_receipt_prov['sessionMissingPath']!r} "
            "不存在 ⇒ 拒绝（不能默默跳过 session 身份校验）")

    s1 = derive_enabled_set(candidate)
    ground = load_ground(ground_path)
    # **v5 productY 优先**：root 实测值写回在候选的 v5Ground.productY 里；
    # 统装 `editorOffset` 由总装施加一次，本模块**不施加偏移**。
    v5 = (candidate.get("v5Ground") or {}).get("productY") or {}
    v5_not_filled = (candidate.get("v5Ground") or {}).get("notFilled") or {}
    for r in s1["rows"]:
        ref = r[0]
        if ref in v5_not_filled:
            raise EntryError("GROUND_SAMPLE_MISSING",
                             f"{ref} 是 source-boundary-uncertain（{v5_not_filled[ref].get('why')}）"
                             "⇒ **不裁定、不填**；无法进入生产")
        smp = ground["sampler"].sample(r[3][0], r[3][2])
        if not smp.get("hasSample"):
            raise EntryError("GROUND_SAMPLE_MISSING", f"{ref} {smp.get('reason')}")
        if ref in v5:
            ground["samples"][ref] = {
                "groundY": float(v5[ref]), "cell": smp.get("cell"), "code": smp.get("code"),
                "source": "v5Ground.productY（root 实测 product 坐标；editorOffset 由总装施加一次）"}
        else:
            ground["samples"][ref] = {
                "groundY": smp["groundY"], "cell": smp.get("cell"), "code": smp.get("code"),
                "source": "shared sampler（**awaiting-v5-value**；旧值不得冒充 v5）"}
    s2 = plan_creation(s1, ground, ctx)
    s3 = assert_template_native(candidate)
    s4 = resolve_behaviour_params(
        candidate, semantic_ids,
        receipt_path=semantic_receipt_prov.get("path"),
        receipt_sha256=semantic_receipt_prov.get("sha256"),
        operation=semantic_receipt_prov.get("operation"),
        session_file=semantic_receipt_prov.get("sessionFile"),
        session_sha256=semantic_receipt_prov.get("sessionSha256"),
        require_session_proof=bool(execute),
        target_level_id=ctx.get("levelId"))
    plan_dir = Path(ctx.get("planDir") or (REPO / ".runtime-verify/combat-build-plans"))
    s5 = build_graph_plan(candidate, s1, s4["currencyId"], plan_dir)

    # ---- **execute 关卡守卫 + 操作级独占目录**（gap 4 + 独占 intent）----
    exec_guard = None
    op_dir = None
    if execute:
        # **先开操作目录**：关卡守卫会执行真实只读链（scene_cli inspect + decode），
        # 这些命令必须有操作级 journal 归属，否则 run_cmd 会拒。
        op_dir = open_operation(ctx.get("operationId"))
        set_current_operation(op_dir)
        exec_guard = assert_execute_level(ctx)
        # **author 作用域绑定**：必须在**创建实体之前**拿到同一作用域证据，
        # 否则会出现"先建实体、后才发现图不属目标"（author lease 不验本次只读关卡）。
        require_author_scope_binding(ctx, exec_guard.get("sessionIdentity"))

    # ---- **严格按序的真实链**（失败即停在每一步，不跳段）----
    steps: list[dict] = []
    native_ids: dict = {}
    receipts: dict = {}

    # 1) 创建前 inspect（真调，不靠外部预传）
    pre = plan_inspect(ctx, "before-create")
    steps.append({"stage": "inspect-before", "argv": pre["argv"]})
    if execute:
        run_cmd(pre["argv"], execute=True, intent="inspect-before")

    # 2) **逐实体创建 + 逐实体回执取精确 entityId**（不做 6 个后全量差分排序 zip）
    for st in s2["steps"]:
        steps.append({"stage": "create", "ref": st["ref"], "argv": st["argv"]})
        if execute:
            rec = run_cmd(st["argv"], execute=True, intent=f"create:{st['ref']}")
            receipts[st["ref"]] = rec
            native_ids[st["ref"]] = resolve_entity_id_from_receipt(rec, st["ref"])

    # 3) fresh 后 inspect 核对（**核验**，不再用它猜 ID）
    post = plan_inspect(ctx, "after-create")
    steps.append({"stage": "inspect-after", "argv": post["argv"]})
    if execute:
        run_cmd(post["argv"], execute=True, intent="inspect-after")

    if not native_ids and entity_before is not None and entity_after is not None:
        # 仅离线/回放用：**必须自己带 ref→id** 的映射，不接受排序 zip
        raise EntryError("NATIVE_ID_RECEIPT_MISSING",
                         "离线回放不接受按排序差分的 native_ids；请提供 ref→entityId 映射")

    s6 = (bind_entities_to_graph(s1, s5, native_ids) if native_ids
          else {"bindingCount": 0, "bindings": [],
                "status": "NEEDS_ENTITY_RECEIPTS",
                "why": "entityId 只能来自**该 ref 自己的 create 回执**；不用 None 占位、不 zip"})
    s7 = build_readback_plan(s1, s5)

    # 4) 图：**create → lookup(真 graphId) → inspect0 → build → inspect1 → bind×N → inspect2(确认)**
    graph_lifecycle = []
    for inst in s5["instances"]:
        camp = inst["campRef"]
        inst = dict(inst, graphNativeName=unique_graph_name(ctx, camp))
        lc = build_graph_lifecycle(ctx, inst, None)
        graph_id = None
        confirmed = None

        def step(stage: str, argv: list[str]) -> None:
            steps.append({"stage": stage, "campRef": camp, "argv": argv})

        step("graph-create", lc["create"])
        if execute:
            be_c = graph_backend(
                run_cmd(lc["create"], execute=True, intent=f"graph-create:{camp}"),
                f"graph-create:{camp}")
            if be_c.get("status") != "create-requested-readback-pending":
                raise EntryError("GRAPH_NOT_DERIVED",
                                 f"{camp}: create status={be_c.get('status')!r}")

            # **lookup 取真 graphId**：**只读轮询，每次 poll 用新的 `--request-id`**。
            # 原因：author/backend 可能按 requestId 缓存 ⇒ 复用同一 id 会一直拿旧
            # `lookup-pending`。`create` 只发生一次（上面），轮询有界间隔 + 有限次数。
            import time as _time
            _rid_base = str(ctx.get("requestId"))
            _poll_interval = float(ctx.get("lookupPollIntervalSec", 0.5))
            _max_tries = int(ctx.get("lookupRetries", 5))

            def _lookup_argv(poll_idx: int) -> list[str]:
                _a = list(lc["lookup"])
                for _j, _tok in enumerate(_a):
                    if _tok == "--request-id" and _j + 1 < len(_a):
                        _a[_j + 1] = f"{_rid_base}-{camp}-lookup-p{poll_idx}"
                        break
                return _a

            be_l = graph_backend(
                run_cmd(_lookup_argv(0), execute=True,
                        intent=f"graph-lookup:{camp}:poll0"),
                f"graph-lookup:{camp}:poll0")
            tries = 0
            while be_l.get("status") == "lookup-pending" and tries < _max_tries:
                tries += 1
                if _poll_interval > 0:
                    _time.sleep(_poll_interval)
                be_l = graph_backend(
                    run_cmd(_lookup_argv(tries), execute=True,
                            intent=f"graph-lookup:{camp}:poll{tries}"),
                    f"graph-lookup:{camp}:poll{tries}")
            graph_id = extract_graph_id(be_l, f"graph-lookup:{camp}")
            for key in ("inspect0", "build", "inspect1", "inspect2"):
                lc[key] = replace_graph_id(lc[key], graph_id)

            # 空图核验
            step("graph-inspect0", lc["inspect0"])
            st0 = parse_graph_state(graph_backend(
                run_cmd(lc["inspect0"], execute=True, intent=f"graph-inspect0:{camp}"),
                f"graph-inspect0:{camp}"))
            if st0["nodeCount"] != 0:
                raise EntryError("GRAPH_NOT_DERIVED",
                                 f"{camp}: 新图 nodeCount={st0['nodeCount']} != 0")

            # build（--graph-id 已是真值）
            step("graph-build", lc["build"])
            graph_backend(run_cmd(lc["build"], execute=True, intent=f"graph-build:{camp}"),
                          f"graph-build:{camp}")

            # 节点数核验
            step("graph-inspect1", lc["inspect1"])
            st1 = parse_graph_state(graph_backend(
                run_cmd(lc["inspect1"], execute=True, intent=f"graph-inspect1:{camp}"),
                f"graph-inspect1:{camp}"))
            if st1["nodeCount"] != inst["nodeCount"]:
                raise EntryError("GRAPH_DANGLING",
                                 f"{camp}: build 后 nodeCount={st1['nodeCount']} != "
                                 f"计划 {inst['nodeCount']}")

            # **逐实体 bind**（各带唯一 requestId）；回执**不当成功**
            my_ids = []
            for b in (s6.get("bindings") or []):
                if b["campRef"] != camp:
                    continue
                my_ids.append(int(b["nativeId"]))
                argv = plan_bind_argv(ctx, inst, graph_id, b["entityRef"],
                                      b["nativeId"], st1["nodeCount"])
                step("graph-bind", argv)
                assert_bind_requested(
                    graph_backend(run_cmd(argv, execute=True,
                                          intent=f"graph-bind:{camp}:{b['entityRef']}"),
                                  f"graph-bind:{camp}:{b['entityRef']}"),
                    f"graph-bind:{camp}:{b['entityRef']}")
            lc["binds"] = my_ids

            # **inspect2 确认绑定**：boundEntityIds ⊆ 计划目标 + graphId 一致 + 节点原件
            # `boundToLevel` **按该图的宿主类型条件化**（怪物宿主图 false 是正常的）
            step("graph-inspect2", lc["inspect2"])
            st2 = parse_graph_state(graph_backend(
                run_cmd(lc["inspect2"], execute=True, intent=f"graph-inspect2:{camp}"),
                f"graph-inspect2:{camp}"))
            plan_defs = graph_node_defs(candidate, camp)
            confirmed = assert_bound_confirmed(
                st2, my_ids, f"graph-inspect2:{camp}",
                graph_id=graph_id,
                host_kind=str(inst.get("hostKind") or "monster-host"),
                expected_node_defs=plan_defs or None)
        else:
            for key in ("lookup", "inspect0", "build", "inspect1", "inspect2"):
                step(f"graph-{key}", lc[key])

        graph_lifecycle.append({
            "campRef": camp, "graphName": lc["graphName"], "graphId": graph_id,
            "argv": {k: lc[k] for k in ("create", "lookup", "inspect0", "build",
                                        "inspect1", "inspect2")},
            "requestIds": lc["requestIds"],
            "bindConfirmedBy": "graph inspect2 → boundEntityIds",
            "confirmed": confirmed,
            "graphIdSource": "graph lookup → backend.graphId（注入后续每一步 --graph-id）",
        })

    # 5) 读回（S7 真执行）
    readback_runs = []
    for op in s7["ops"]:
        if not op.get("argv"):
            continue
        argv = list(op["argv"])
        if any("<" in str(a) for a in argv):
            raise EntryError("DISPATCH_CONTEXT_MISSING",
                             f"{op['id']} argv 仍有占位：{argv}；需 ctx 提供真实路径")
        steps.append({"stage": "readback", "op": op["id"], "argv": argv})
        if execute:
            readback_runs.append(run_cmd(argv, execute=True, intent=f"readback:{op['id']}"))

    # 6) **保存由统一层控制**：本模块**不擅自提前保存**
    save_argv = None       # 由总装发起；此处只声明契约

    execution = {
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "strictOrder": ["inspect-before", "create*(独立 review)", "inspect-after",
                        "graph-create(唯一名)", "graph-lookup(真 graphId)",
                        "graph-inspect0(空图)", "graph-build(--graph-id=真值)",
                        "graph-inspect1(节点数)", "graph-bind*(逐实体)",
                        "graph-inspect2(boundEntityIds 确认)",
                        "readback", "save(unified-layer only)"],
        "bindIsNotSuccess": "bind 回执恒为 `binding-requested-readback-pending`；"
                            "成功唯一判据 = inspect2.boundEntityIds 含全部目标实体",
        "steps": steps,
        "nativeIds": native_ids,
        "receipts": sorted(receipts),
        "graphLifecycle": graph_lifecycle,
        "readbackRuns": len(readback_runs),
        "saveControlledBy": "unity-layer（本模块**不擅自保存**）",
        "saveArgvTemplate": ([sys.executable, "-B", str(REPO / ENTRY_SCENE_CLI), "save",
                              "--session", str(ctx.get("session") or ""),
                              "--level-id", str(ctx.get("levelId") or ""),
                              "--review", "<per-run review>",
                              "--elevated-queue", str(ctx.get("queue") or "")]
                             if False else None),
        "abortPolicy": "任一命令 returncode!=0 或业务 ok=false ⇒ RunAbort（**失败即停，不重放**）",
        "rawExceptionPolicy": "raw 异常不重放（保留完整 stdout/stderr/intent）",
        "noZipGuessing": "**已实现**：entityId 只来自 `resolve_entity_id_from_receipt()` 读该 ref **自己的 create 回执**；`bind_entities_to_graph` 只接受 ref→entityId 字典，**拒绝排序列表 zip**（离线回放也拒）。",
    }

    return {
        "ok": True, "tool": TOOL, "module": MODULE, "contractVersion": CONTRACT_VERSION,
        "segments": {
            "S1_enabledSet": {"implemented": True, "code": "derive_enabled_set", **s1},
            "S2_creation": {"implemented": True, "code": "plan_creation", **s2},
            "S3_nativeComponents": {"implemented": True, "code": "assert_template_native", **s3},
            "S4_behaviourParams": {"implemented": True, "code": "resolve_behaviour_params", **s4},
            "S5_graph": {"implemented": True, "code": "build_graph_plan", **s5},
            "S6_binding": {"implemented": True, "code": "bind_entities_to_graph", **s6},
            "S7_readback": {"implemented": True, "code": "build_readback_plan", **s7},
        },
        "execution": execution,
        "ground": {"path": ground["path"], "sha256": ground["sha256"],
                   "cells": ground["cells"]},
        "semanticIds": {"status": "RESOLVED" if s4["semanticIdResolved"] else "MISSING",
                        "currencyId": s4["currencyId"], "typed": s4["currencyTyped"]},
        "entryPoints": {"sceneCli": ENTRY_SCENE_CLI, "author": ENTRY_AUTHOR,
                        "fieldDiff": ENTRY_FIELD_DIFF, "props": ENTRY_PROPS},
        "errorCodes": sorted(ERROR_CODES),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="production_entry.py", description=__doc__)
    p.add_argument("--ground", default=None)
    p.add_argument("--semantic-ids", default=None)
    p.add_argument("--session", default=None)
    p.add_argument("--level-id", type=int, default=None)
    # 关卡原生身份由既有只读链新鲜取得（scene_cli inspect → readonly_profile decode），
    # **不需要**用户另填 pid/bridge/inspect 事实文件。
    # 唯一新增的真实产物参数：new-scope.py 的 scope JSON（固定 scope 契约，非自造 schema）
    p.add_argument("--author-scope", default=None,
                   help="**仅离线审阅用显式覆盖**；execute 正常路径由 --run-id 自动派生 "
                        "(.runtime/editor-bridge/runs/<run-id>/bridge-settings.json，"
                        "六字段 pid/startUtcTicks/nonce/pipeName/expiresUtc/expectedExe)")
    # **操作级显式 operation-id**：journal 独占目录；已存在即拒，不自动换 uuid
    p.add_argument("--operation-id", default=None,
                   help="execute 必需：操作级独占 id（[A-Za-z0-9][A-Za-z0-9._-]{0,95}）")
    p.add_argument("--review", default=None,
                   help="**仅限单个实体**时的 review；多实体必须用 --reviews-json")
    p.add_argument("--reviews-json", default=None,
                   help="ref→review 路径 的 JSON 映射（**每实体独立 review**，禁复用）")
    p.add_argument("--elevated-queue", default=None)
    p.add_argument("--plan-dir", default=None)
    p.add_argument("--request-id", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--before-gil", default=None)
    p.add_argument("--after-gil", default=None)
    # ---- 生产战斗验收（r23）
    p.add_argument("--combat-acceptance", action="store_true",
                   help="走**生产战斗验收入口**：真实 before/after run → decode_bound → "
                        "身份校验 → 两断言")
    p.add_argument("--before-run", default=None, help="攻击前 run 目录（含 acceptance.bin）")
    p.add_argument("--after-run", default=None, help="攻击后 run 目录")
    p.add_argument("--vitals-card", default=None, help="绑定的 vitals card JSON")
    p.add_argument("--targets", default=None, help="逗号分隔的 monster runtimeId")
    # ---- 双来源（r24）：contact-state v8
    p.add_argument("--dual-acceptance", action="store_true",
                   help="vitals + contact **双来源**读回与身份连接")
    p.add_argument("--before-contact-run", default=None)
    p.add_argument("--after-contact-run", default=None)
    p.add_argument("--contact-card", default=None)
    p.add_argument("--receipts", default=None,
                   help="创建 receipt 的 ref→editorInstanceGuid JSON（精确匹配用）")
    p.add_argument("--entity-before", default=None, help="创建前实体表 JSON")
    p.add_argument("--entity-after", default=None, help="创建后实体表 JSON")
    p.add_argument("--execute", action="store_true", help="**真调**既有入口（默认 dry-run）")
    p.add_argument("--out", default=None)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)

    # ---- 双来源验收入口（r24）：vitals + contact，缺任一侧 ⇒ NO_RUN_DATA
    if getattr(a, "dual_acceptance", False):
        need = [n for n, v in (("--before-run", a.before_run),
                               ("--after-run", a.after_run),
                               ("--vitals-card", a.vitals_card),
                               ("--before-contact-run", a.before_contact_run),
                               ("--after-contact-run", a.after_contact_run),
                               ("--contact-card", a.contact_card)) if not v]
        if need:
            print(json.dumps({"ok": False, "accepted": False,
                              "status": "NO_RUN_DATA", "code": "RUN_DATA_MISSING",
                              "sources": ["vitals-state", "contact-state"],
                              "detail": f"缺 {need} ⇒ **两侧 run 数据不全，未验收**"
                                        "（不构造值）"},
                             ensure_ascii=False, indent=1))
            return 3
        try:
            vc = read_json(a.vitals_card)
            cc = read_json(a.contact_card)
            rc = read_json(a.receipts) if a.receipts else {}
            # **生产驱动接线**：只有显式 `--execute` 且 session/target-level 齐备时
            # 才构造 driver ⇒ `assert_dual_source_identity` 会用 `native_card_reader`
            # （⇒ `invoke_native_card` 三步：prepare → 核身份 → dispatch → decode）。
            # 缺任一前置 ⇒ driver=None，调用方必须自备已解码的 run，**不伪造驱动**。
            _drv_session = getattr(a, "session", None)
            _drv_level = getattr(a, "target_level", None)
            _driver = None
            if getattr(a, "execute", False) and _drv_session and _drv_level:
                _driver = {"session": _drv_session,
                           "targetLevelId": _drv_level,
                           "previousRun": getattr(a, "previous_run", None),
                           "execute": True,
                           "prepared": None,
                           "queue": getattr(a, "elevated_queue", None)}
            out = assert_dual_source_identity(
                before_vitals=a.before_run, after_vitals=a.after_run,
                before_contact=a.before_contact_run,
                after_contact=a.after_contact_run,
                vitals_card=vc, contact_card=cc, receipts=rc,
                driver=_driver,
                run_id=getattr(a, "run_id", None))
        except RunAbort as exc:
            # **RunAbort 不是 EntryError 子类**（两者都是 RuntimeError 的兄弟）⇒
            # 必须单独捕获，否则会漏成 traceback。未知 ≠ 失败 ≠ 成功。
            print(json.dumps({"ok": False, "outcomeUnknown": True, "state": "UNKNOWN",
                              "code": "RUN_ABORT", "detail": str(exc),
                              "replayForbidden": True}, ensure_ascii=False, indent=1))
            return 3
        except EntryError as exc:
            print(json.dumps({"ok": False, "accepted": False, "code": exc.code,
                              "detail": exc.detail}, ensure_ascii=False, indent=1))
            return 2
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out.get("accepted") else 1

    # ---- 生产战斗验收入口（r23）：真实 run 才走，无数据则明确「未验收」
    if getattr(a, "combat_acceptance", False):
        missing = [n for n, v in (("--before-run", a.before_run),
                                  ("--after-run", a.after_run),
                                  ("--vitals-card", a.vitals_card)) if not v]
        if missing:
            print(json.dumps({"ok": False, "accepted": False,
                              "status": "NO_RUN_DATA",
                              "code": "VITALS_RUN_MISSING",
                              "detail": f"缺 {missing} ⇒ **无真实 run 数据，未验收**（不构造值）"},
                             ensure_ascii=False, indent=1))
            return 3
        try:
            card = read_json(a.vitals_card)
            tgt = ([int(x) for x in a.targets.split(",") if x.strip()]
                   if a.targets else None)
            out = assert_combat_acceptance(before_run=a.before_run,
                                           after_run=a.after_run,
                                           card=card, targets=tgt)
        except RunAbort as exc:
            # 同上：RunAbort 非 EntryError 子类，必须单独结构化收口
            print(json.dumps({"ok": False, "accepted": False, "outcomeUnknown": True,
                              "state": "UNKNOWN", "code": "RUN_ABORT",
                              "detail": str(exc), "replayForbidden": True},
                             ensure_ascii=False, indent=1))
            return 3
        except EntryError as exc:
            print(json.dumps({"ok": False, "accepted": False, "code": exc.code,
                              "detail": exc.detail}, ensure_ascii=False, indent=1))
            return 2
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out.get("accepted") else 1

    reviews = {}
    if getattr(a, "reviews_json", None):
        reviews = json.loads(Path(a.reviews_json).read_text(encoding="utf-8-sig"))
    ctx = {"session": a.session, "levelId": a.level_id, "review": a.review,
           "reviews": reviews,
           "requestId": getattr(a, "request_id", None),
           "runId": getattr(a, "run_id", None),
           "beforeGil": getattr(a, "before_gil", None),
           "afterGil": getattr(a, "after_gil", None),
           "queue": a.elevated_queue, "planDir": a.plan_dir,
           # 关卡原生身份在 execute 内部由既有只读链取得，不需要额外事实文件参数
           "authorScope": (read_json(a.author_scope)
                           if getattr(a, "author_scope", None) else None),
           "operationId": getattr(a, "operation_id", None)}
    eb = read_json(a.entity_before) if a.entity_before else None
    ea = read_json(a.entity_after) if a.entity_after else None
    try:
        plan = run_entry(ground_path=a.ground, semantic_ids_path=a.semantic_ids, ctx=ctx,
                         execute=a.execute, entity_before=eb, entity_after=ea)
    except RunAbort as exc:
        # **结构化 UNKNOWN**：超时/未知/无法判定 ≠ 失败 ≠ 成功。
        # **不重建 operation、不自动重放**；给出最终状态文件位置供读回定位。
        op = current_operation()
        final = None
        try:
            if op is not None:
                final = close_operation(op, state="UNKNOWN",
                                        payload={"abort": str(exc), "kind": "RunAbort"})
        except EntryError:
            final = None
        print(json.dumps({"ok": False, "outcomeUnknown": True, "state": "UNKNOWN",
                          "code": "RUN_ABORT", "detail": str(exc),
                          "operationDir": str(op) if op else None,
                          "finalRecord": str(final) if final else None,
                          "replayForbidden": True,
                          "note": "逐字节原件在 operation 目录的 *-unknown.json"}, ensure_ascii=False, indent=1))
        return 3
    except EntryError as exc:
        op = current_operation()
        try:
            if op is not None:
                close_operation(op, state="FAILED",
                                payload={"code": exc.code, "detail": exc.detail})
        except EntryError:
            pass
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail,
                          "operationDir": str(op) if op else None},
                         ensure_ascii=False, indent=1))
        return 2
    if a.execute and current_operation() is not None:
        # **COMPLETED 落盘失败不得吞**：若最终状态写不进去，本模块**不能**仍报 ok
        # （否则"成功"这一结论没有持久证据）。
        try:
            close_operation(current_operation(), state="COMPLETED")
        except EntryError as exc:
            print(json.dumps({"ok": False, "state": "UNKNOWN",
                              "outcomeUnknown": True,
                              "code": "OPERATION_FINAL_STATE_WRITE_FAILED",
                              "detail": exc.detail,
                              "operationDir": str(current_operation()),
                              "replayForbidden": True,
                              "note": "业务链已走完，但 COMPLETED 最终状态未落盘 ⇒ 不得声称成功"},
                             ensure_ascii=False, indent=1))
            return 3
    text = json.dumps(plan, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": a.out}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
