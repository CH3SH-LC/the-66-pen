"""kind-37 卡片的**独立验收器**（对象③ revision 9）。

本文件按 lead 逐行审出的四个缺陷返工（**真修，不是只 fail-closed**）：

1. **独立重算组件表**：从原始回执负载里按 ``receipt-layout.json`` 声明的 ``components`` 段
   （``beforeOffset/beforeCount/afterOffset/afterCount/stride`` + 每行字段偏移）自己解码
   **before / after 两张组件表**，并核对**完整既有组件集合**。
2. **``prefixPreserved`` 不得同义反复**：不再用"首个差异之前的字节相等"（那是 ``first_difference``
   的定义）⇒ 改为**集合包含判定**：before 表每一行都必须能在 after 表里按身份
   ``(kind, entityId, itemId, count, trigger)`` 找到。
3. **配置具名固定解码**：只按固定词表 ``("kind","entityId","itemId","count","trigger")`` 从
   layout 的 ``kind37Config`` 段取**偏移**（编译期 layout，**不接受 caller 给的任意 offset**，
   否则会把魔数当配置）；caller 只能给**期望值**。
4. **baseline 同结构比较**：只比 ``snapshot{offset,length}`` 声明的那一段
   （GameContextSnapshot vs 负载里嵌入的同一结构），**不拿它比整个 HookReceipt 头**。

仍然：纯 stdlib、独立解 ``stdout.jsonl``、**不信任生成器 summary**、缺件具名拒绝。

``validate_run(run)`` / ``validate_artifacts(artifacts)`` 返回
``ok, levelId, actionCode, receiptVersion, specSha256, rawSha256,
mutationVerified, prefixPreserved, configurationVerified`` + ``refusals/diagnostics``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

__all__ = [
    "AcceptanceError",
    "KIND37_CONFIG_WORDS",
    "REQUIRED_RESULT_FIELDS",
    "ROW_IDENTITY_WORDS",
    "decode_components",
    "decode_hex",
    "decode_kind37_config",
    "first_difference",
    "layout_value",
    "read_run",
    "sha256_bytes",
    "validate_artifacts",
    "validate_run",
]

REQUIRED_RESULT_FIELDS = ("ok", "levelId", "actionCode", "receiptVersion", "specSha256",
                          "rawSha256", "mutationVerified", "prefixPreserved",
                          "configurationVerified")

MAGIC = 0x31524847                       # 'GHR1'，与共享 hook 的 receipt magic 一致
RAW_FILES = ("stdout.jsonl", "raw.jsonl", "probe-stdout.jsonl")

#: kind-37 配置的**固定词表**（顺序即 layout 段键名）。caller 只能给这些名字的期望值。
KIND37_CONFIG_WORDS = ("kind", "entityId", "itemId", "count", "trigger")

#: 组件行的身份字段（"既有组件是否被保留"的集合判定用）。
ROW_IDENTITY_WORDS = ("kind", "entityId", "itemId", "count", "trigger")


class AcceptanceError(RuntimeError):
    """具名拒绝（``code`` 供调用方分支）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_hex(text: str, what: str) -> bytes:
    if not isinstance(text, str) or not text or len(text) % 2:
        raise AcceptanceError("hex_invalid", f"{what}: 不是非空偶数长度十六进制串")
    try:
        return bytes.fromhex(text)
    except ValueError as error:
        raise AcceptanceError("hex_invalid", f"{what}: {error}") from None


def layout_value(layout: dict, section: str, key: str) -> int:
    """从 ``receipt-layout.json`` 取偏移/尺寸；缺段缺键一律 ``layout_incomplete``。"""
    block = layout.get(section) if isinstance(layout, dict) else None
    if not isinstance(block, dict) or key not in block:
        raise AcceptanceError("layout_incomplete", f"{section}.{key}")
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AcceptanceError("layout_incomplete", f"{section}.{key} 不是非负整数：{value!r}")
    return value


def first_difference(left: bytes, right: bytes) -> dict:
    """首个差异（**只作诊断**，不再充当 prefixPreserved 的证据）。"""
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return {"equal": False, "offset": index, "baselineByte": left[index],
                    "observedByte": right[index], "baselineLength": len(left),
                    "observedLength": len(right)}
    if len(left) != len(right):
        return {"equal": False, "offset": limit, "baselineByte": None, "observedByte": None,
                "baselineLength": len(left), "observedLength": len(right)}
    return {"equal": True, "offset": None, "baselineLength": len(left),
            "observedLength": len(right)}


def _read_uint(payload: bytes, offset: int, size: int, endian: str = "little") -> int:
    if offset < 0 or size <= 0 or offset + size > len(payload):
        raise AcceptanceError("offset_out_of_range", f"@{offset}+{size} > {len(payload)}")
    return int.from_bytes(payload[offset:offset + size], endian)


# ---------------------------------------------------------------------------
# 具名固定解码（缺陷 1 & 3）
# ---------------------------------------------------------------------------


def decode_components(payload: bytes, layout: dict, side: str) -> list[dict]:
    """按 layout 的 ``components`` 段解码一张组件表（``side`` ∈ before/after）。

    layout 形状（全部来自编译期 layout probe）::

        "components": {"beforeOffset":…, "beforeCount":…, "afterOffset":…, "afterCount":…,
                       "stride":…, "kind":…, "entityId":…, "itemId":…, "count":…, "trigger":…}
    """
    if side not in ("before", "after"):
        raise AcceptanceError("bad_side", side)
    offset = layout_value(layout, "components", side + "Offset")
    count = layout_value(layout, "components", side + "Rows")   # 行数键名与生成器一致
    stride = layout_value(layout, "components", "stride")
    if count == 0:
        return []
    fields = {name: layout_value(layout, "components", name) for name in ROW_IDENTITY_WORDS}
    size = max(fields.values()) + 4
    if size > stride:
        raise AcceptanceError("layout_incomplete", f"字段偏移超出 stride（{size} > {stride}）")
    rows = []
    for index in range(count):
        base = offset + index * stride
        if base + stride > len(payload):
            raise AcceptanceError("offset_out_of_range",
                                  f"components.{side}[{index}] @{base} 超出负载 {len(payload)}")
        rows.append({name: _read_uint(payload, base + fields[name], 4) for name in ROW_IDENTITY_WORDS})
    return rows


def decode_kind37_config(payload: bytes, layout: dict) -> dict:
    """**具名固定解码** kind-37 配置：词表固定，偏移只从 layout 取（caller 不能给 offset）。"""
    values = {}
    for word in KIND37_CONFIG_WORDS:
        offset = layout_value(layout, "kind37Config", word)
        size = layout_value(layout, "kind37Config", word + "Size")
        values[word] = _read_uint(payload, offset, size)
    return values


def _row_identity(row: dict) -> tuple:
    return tuple(row.get(name) for name in ROW_IDENTITY_WORDS)


# ---------------------------------------------------------------------------
# 原始件读取
# ---------------------------------------------------------------------------


def read_run(run: Path) -> dict:
    """把一个 run 目录读成 ``{相对名: bytes}``（缺件交给验收核心具名拒绝）。"""
    run = Path(run)
    if not run.is_dir():
        raise AcceptanceError("run_missing", str(run))
    artifacts: dict = {}
    for path in sorted(run.rglob("*")):
        if path.is_file():
            artifacts[path.relative_to(run).as_posix()] = path.read_bytes()
    return artifacts


def _name(artifacts: dict, *candidates: str) -> str | None:
    for name in candidates:
        if name in artifacts:
            return name
    return None


def _bytes(artifacts: dict, name: str) -> bytes:
    if name not in artifacts:
        raise AcceptanceError("file_missing", name)
    return artifacts[name]


def _json(artifacts: dict, name: str):
    try:
        return json.loads(_bytes(artifacts, name).decode("utf-8"))
    except json.JSONDecodeError as error:
        raise AcceptanceError("json_invalid", f"{name}: {error}") from None


def _raw_lines(artifacts: dict) -> tuple[list[dict], str]:
    name = _name(artifacts, *RAW_FILES)
    if name is None:
        raise AcceptanceError("raw_missing", f"没有 {RAW_FILES} 之一")
    text = artifacts[name].decode("utf-8")
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise AcceptanceError("raw_line_invalid", f"{name}:{number}: {error}") from None
        if not isinstance(record, dict):
            raise AcceptanceError("raw_line_invalid", f"{name}:{number}: 不是 JSON 对象")
        records.append(record)
    return records, text


def _payload_from(records: list[dict], layout: dict) -> tuple[bytes, dict]:
    """取原始回执负载；长度以 layout 的 ``raw.snapshotHexLength`` 为准。"""
    try:
        want = layout_value(layout, "raw", "snapshotHexLength")
    except AcceptanceError:
        want = None
    for record in reversed(records):
        for candidate in ("snapshotHex", "receiptHex", "payloadHex"):
            if candidate in record:
                payload = decode_hex(record[candidate], candidate)
                if want is not None and len(payload) != want:
                    raise AcceptanceError("payload_length_mismatch",
                                          f"{candidate} 长度 {len(payload)} != layout {want}")
                return payload, {"source": candidate,
                                 "lengthRule": (f"layout raw.snapshotHexLength={want}"
                                                if want is not None else "以 hex 自身长度为准")}
    if want is None:
        raise AcceptanceError("layout_incomplete", "raw.snapshotHexLength")
    raise AcceptanceError("raw_missing", "raw 行里没有 snapshotHex/receiptHex/payloadHex")


# ---------------------------------------------------------------------------
# 主验收
# ---------------------------------------------------------------------------


def validate_run(run) -> dict:
    """独立验收一个候选 run 目录（读盘后交给 :func:`validate_artifacts`）。"""
    run = Path(run).resolve()
    return validate_artifacts(read_run(run), label=str(run))


def validate_artifacts(artifacts: dict, *, label: str = "<memory>") -> dict:
    """验收核心：只吃 ``{相对名: bytes}``，不碰文件系统。"""
    prepared = _json(artifacts, "prepared.json")
    build = _json(artifacts, "build-result.json")
    spec_name = _name(artifacts, "normalized-spec.json")
    if spec_name is None:
        raise AcceptanceError("file_missing", "normalized-spec.json")
    spec_bytes = artifacts[spec_name]
    spec = _json(artifacts, spec_name)
    layout = _json(artifacts, "receipt-layout.json")
    records, raw_text = _raw_lines(artifacts)

    result: dict = {
        "run": label, "ok": False,
        "levelId": None, "actionCode": None, "receiptVersion": None,
        "specSha256": sha256_bytes(spec_bytes),
        "rawSha256": sha256_bytes(raw_text.encode("utf-8")),
        "mutationVerified": False, "prefixPreserved": False, "configurationVerified": False,
        "refusals": [], "diagnostics": {},
    }

    def refuse(code: str, detail: str) -> None:
        result["refusals"].append({"code": code, "detail": detail})

    # ---- 1. spec 绑定
    for key in ("levelId", "actionCode", "receiptVersion", "kind", "hosts",
                "mutation", "configuration"):
        if key not in spec:
            refuse("spec_fields_missing", key)
            return result
    result["levelId"] = int(spec["levelId"])
    result["actionCode"] = int(spec["actionCode"])
    result["receiptVersion"] = int(spec["receiptVersion"])
    if int(spec["kind"]) != 37:
        refuse("spec_kind_not_37", f"kind={spec['kind']!r}")
    if not spec["hosts"]:
        refuse("spec_hosts_empty", "hosts 为空")
    if prepared.get("normalizedSpecSha256") and prepared["normalizedSpecSha256"] != result["specSha256"]:
        refuse("spec_sha_mismatch_prepared",
               f"{prepared['normalizedSpecSha256']} != {result['specSha256']}")

    # ---- 2. 生成器 summary 只作旁证
    if build.get("ok") and not build.get("compiled"):
        refuse("build_result_claims_ok_without_compile", "ok=true 但 compiled=false")
    result["diagnostics"]["generatorSummary"] = {
        "buildOk": build.get("ok"), "launchable": build.get("launchable"),
        "compileOnly": build.get("compileOnly"), "called": build.get("called"),
        "note": "仅作旁证；判定不读它"}

    # ---- 3. 原始负载 + 回执身份（偏移全部来自 layout）
    payload, payload_info = _payload_from(records, layout)
    result["diagnostics"]["payload"] = payload_info
    magic = _read_uint(payload, layout_value(layout, "receipt", "magic"), 4)
    version = _read_uint(payload, layout_value(layout, "receipt", "version"), 4)
    nonce = _read_uint(payload, layout_value(layout, "receipt", "nonce"), 8)
    if magic != MAGIC:
        refuse("receipt_magic_mismatch", f"0x{magic:08x} != 0x{MAGIC:08x}")
    if version != result["receiptVersion"]:
        refuse("receipt_version_mismatch", f"{version} != {result['receiptVersion']}")
    if prepared.get("nonce") is not None and int(prepared["nonce"]) != nonce:
        refuse("receipt_nonce_mismatch", f"{nonce} != prepared {prepared['nonce']}")

    # ---- 4. baseline：**只比 snapshot 段**（同结构），不比整个回执头
    baseline_name = _name(artifacts, "baseline-snapshot.bin")
    if baseline_name is None:
        refuse("baseline_missing", "baseline-snapshot.bin")
    else:
        baseline = artifacts[baseline_name]
        if prepared.get("baselineSha256") and prepared["baselineSha256"] != sha256_bytes(baseline):
            refuse("baseline_sha_mismatch",
                   f"{prepared['baselineSha256']} != {sha256_bytes(baseline)}")
        snap_offset = layout_value(layout, "snapshot", "offset")
        snap_length = layout_value(layout, "snapshot", "length")
        if snap_offset + snap_length > len(payload) or snap_length > len(baseline):
            refuse("snapshot_slice_out_of_range",
                   f"snapshot @{snap_offset}+{snap_length} payload={len(payload)} "
                   f"baseline={len(baseline)}")
        else:
            embedded = payload[snap_offset:snap_offset + snap_length]
            result["diagnostics"]["snapshotComparison"] = first_difference(baseline[:snap_length],
                                                                          embedded)

    # ---- 5. 组件表：**独立重算** + 完整既有集合核对
    before = decode_components(payload, layout, "before")
    after = decode_components(payload, layout, "after")
    result["diagnostics"]["beforeRows"] = before
    result["diagnostics"]["afterRows"] = after
    before_ids = [_row_identity(row) for row in before]
    after_ids = {_row_identity(row) for row in after}
    missing = [ident for ident in before_ids if ident not in after_ids]
    if missing:
        refuse("existing_components_not_retained", f"after 表里找不到 {missing}")
    result["prefixPreserved"] = bool(before) and not missing
    if not before:
        refuse("before_table_empty", "before 组件表为空 ⇒ 无法证明既有组件被保留")

    plan = spec.get("mutation") or {}
    added = [ident for ident in after_ids if ident not in set(before_ids)]
    if not plan.get("declared"):
        refuse("mutation_not_declared", "spec.mutation.declared != true")
    elif not added:
        refuse("mutation_absent", "after 表没有新增组件")
    else:
        expected_added = plan.get("addedRow")
        if expected_added is not None:
            want = tuple(expected_added.get(word) for word in ROW_IDENTITY_WORDS)
            if want not in after_ids:
                refuse("mutation_row_mismatch", f"期望新增 {want}，实测 {added}")
            else:
                result["mutationVerified"] = True
        else:
            result["mutationVerified"] = True
        if len(added) != int(plan.get("addedCount", 1)):
            refuse("mutation_count_mismatch",
                   f"新增 {len(added)} 行 != spec {plan.get('addedCount', 1)}")

    # ---- 6. 配置：**具名固定解码**（词表固定；caller 的 offset 一概不接受）
    configuration = spec.get("configuration") or {}
    expected = configuration.get("expected")
    # 缺陷 3：**任何** caller 给的 offset 都直接拒（无论有没有 expected）——否则会把魔数当配置
    if "offset" in configuration:
        refuse("configuration_word_table_required",
               "caller 给的 offset 一律不接受；配置只能按固定词表 "
               f"{KIND37_CONFIG_WORDS} 从 layout 解码")
    if not isinstance(expected, dict) or not expected:
        refuse("configuration_not_declared",
               "spec.configuration.expected 为空 ⇒ 无法核对配置（不静默通过）")
    else:
        unknown = [name for name in expected if name not in KIND37_CONFIG_WORDS]
        if unknown:
            refuse("configuration_word_not_in_table", ",".join(sorted(unknown)))
        decoded = decode_kind37_config(payload, layout)
        result["diagnostics"]["configurationDecoded"] = decoded
        for name, want in expected.items():
            if name in decoded and int(decoded[name]) != int(want):
                refuse("configuration_value_mismatch", f"{name} = {decoded[name]} != {want}")
        result["configurationVerified"] = bool(decoded) and not any(
            r["code"].startswith("configuration_") for r in result["refusals"])

    result["ok"] = bool(result["mutationVerified"] and result["prefixPreserved"]
                        and result["configurationVerified"] and not result["refusals"])
    result["code"] = "ACCEPTED" if result["ok"] else "REFUSED"
    return result


# ---------------------------------------------------------------------------
# 自检（内存构造；缺陷 2/3 各有反例）
# ---------------------------------------------------------------------------


def _fixture(*, tamper_summary: bool = False, drop_layout_key: bool = False,
             drop_existing_row: bool = False, config_expected: dict | None = None,
             caller_offset: bool = False) -> dict:
    """内存里的 run 件；布局形状与现实一致：receipt / snapshot / components / kind37Config。"""
    stride = 20
    before_offset, after_offset = 128, 192
    layout = {
        "receipt": {"magic": 0, "version": 4, "nonce": 8, "deadline": 16},
        "snapshot": {"offset": 64, "length": 64},
        "raw": {"snapshotHexLength": 320},
        "components": {"beforeOffset": before_offset, "beforeRows": 2,
                       "afterOffset": after_offset, "afterRows": 2 if drop_existing_row else 3,
                       "stride": stride, "kind": 0, "entityId": 4, "itemId": 8,
                       "count": 12, "trigger": 16},
        "kind37Config": {"kind": 272, "kindSize": 4, "entityId": 276, "entityIdSize": 4,
                         "itemId": 280, "itemIdSize": 4, "count": 284, "countSize": 4,
                         "trigger": 288, "triggerSize": 4},
        "refuseCodes": {"1": "before_failed"},
    }
    if drop_layout_key:
        layout["receipt"].pop("nonce")

    payload = bytearray(320)
    payload[0:4] = MAGIC.to_bytes(4, "little")
    payload[4:8] = (25).to_bytes(4, "little")
    payload[8:16] = (4242).to_bytes(8, "little")
    payload[16:24] = (999999).to_bytes(8, "little")
    payload[64:128] = bytes([0xAB]) * 64                      # 嵌入的 GameContextSnapshot
    baseline = bytearray(64)
    row_a = (8, 1077936130, 0, 1, 0)
    row_b = (1, 1077936131, 0, 1, 0)
    row_new = (37, 1077936132, 1107296259, 1, 7)

    def put(offset: int, row: tuple) -> None:
        for index, name in enumerate(ROW_IDENTITY_WORDS):
            at = offset + layout["components"][name]
            payload[at:at + 4] = int(row[index]).to_bytes(4, "little")

    put(before_offset, row_a)
    put(before_offset + stride, row_b)
    put(after_offset, row_a)
    if drop_existing_row:
        put(after_offset + stride, row_new)          # 反例：row_b 丢了
    else:
        put(after_offset + stride, row_b)
        put(after_offset + 2 * stride, row_new)      # 正常：既有两行都在，末尾新增 kind 37
    for word, value in (("kind", 37), ("entityId", 1077936132), ("itemId", 1107296259),
                        ("count", 1), ("trigger", 7)):
        at = layout["kind37Config"][word]
        payload[at:at + 4] = int(value).to_bytes(4, "little")

    spec = {
        "levelId": 1073741843, "actionCode": 20, "receiptVersion": 25, "kind": 37,
        "hosts": [1077936132],
        "mutation": {"declared": True, "addedCount": 1,
                     "addedRow": {"kind": 37, "entityId": 1077936132, "itemId": 1107296259,
                                  "count": 1, "trigger": 7}},
        "configuration": {
            "expected": config_expected if config_expected is not None
            else {"kind": 37, "entityId": 1077936132, "itemId": 1107296259, "count": 1,
                  "trigger": 7},
        },
    }
    if caller_offset:
        spec["configuration"] = {"offset": 248, "expected": {"kind": 37}}
    spec_bytes = json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8")
    raw = json.dumps({"ok": True, "scope": "FIXED_DROPSTUFF_ATTACH",
                      "snapshotHex": bytes(payload).hex(), "snapshotBytes": len(payload),
                      "receiptNonce": "4242"}) + "\n"
    prepared = {"levelId": 1073741843, "actionCode": 20, "receiptVersion": 25, "nonce": 4242,
                "normalizedSpecSha256": sha256_bytes(spec_bytes),
                "baselineSha256": sha256_bytes(bytes(baseline))}
    build = {"ok": not tamper_summary, "compiled": True, "launchable": not tamper_summary,
             "compileOnly": False, "called": False}
    return {
        "receipt-layout.json": json.dumps(layout).encode("utf-8"),
        "normalized-spec.json": spec_bytes,
        "baseline-snapshot.bin": bytes(baseline),
        "stdout.jsonl": raw.encode("utf-8"),
        "prepared.json": json.dumps(prepared).encode("utf-8"),
        "build-result.json": json.dumps(build).encode("utf-8"),
    }


def selftest() -> dict:
    """6 例自检；**全程内存构造**，零写盘（规则 7：禁止系统 TEMP）。"""
    checks: dict = {"inMemory": True}
    clean = validate_artifacts(_fixture(), label="<clean>")
    checks["acceptsCleanRun"] = clean["ok"]
    checks["cleanResult"] = {key: clean[key] for key in REQUIRED_RESULT_FIELDS}
    checks["cleanDiagnostics"] = {
        "beforeRows": len(clean["diagnostics"].get("beforeRows") or []),
        "afterRows": len(clean["diagnostics"].get("afterRows") or []),
        "config": clean["diagnostics"].get("configurationDecoded"),
    }

    checks["ignoresGeneratorSummary"] = validate_artifacts(
        _fixture(tamper_summary=True))["ok"] is True

    try:
        validate_artifacts(_fixture(drop_layout_key=True))
        checks["layoutIncompleteRefused"] = None
    except AcceptanceError as error:
        checks["layoutIncompleteRefused"] = error.code

    # 缺陷 2 的反例：after 表丢了既有组件 ⇒ 必须拒（不是"首差之前相等"那种同义反复）
    lost = validate_artifacts(_fixture(drop_existing_row=True))
    checks["existingComponentLostRefused"] = [r["code"] for r in lost["refusals"]]
    checks["existingComponentLostPrefix"] = lost["prefixPreserved"]

    # 缺陷 3 的反例：caller 想用任意 offset 读配置 ⇒ 必须拒
    called = validate_artifacts(_fixture(caller_offset=True))
    checks["callerOffsetRefused"] = [r["code"] for r in called["refusals"]]

    # 配置值不符 ⇒ 必须拒
    wrong = validate_artifacts(_fixture(config_expected={"kind": 36, "itemId": 1}))
    checks["configurationMismatchRefused"] = [r["code"] for r in wrong["refusals"]]

    checks["ok"] = bool(checks["acceptsCleanRun"] and checks["ignoresGeneratorSummary"]
                        and checks["layoutIncompleteRefused"] == "layout_incomplete"
                        and "existing_components_not_retained"
                        in checks["existingComponentLostRefused"]
                        and checks["existingComponentLostPrefix"] is False
                        and "configuration_value_mismatch"
                        in checks["configurationMismatchRefused"]
                        and checks["callerOffsetRefused"] == ["configuration_word_table_required"])
    return checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="kind-37 卡片独立验收器（纯 stdlib）")
    parser.add_argument("--run", help="候选 run 目录")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        result = selftest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if not args.run:
        parser.print_help()
        return 2
    try:
        result = validate_run(args.run)
    except AcceptanceError as error:
        print(json.dumps({"ok": False, "code": error.code, "detail": error.detail},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
