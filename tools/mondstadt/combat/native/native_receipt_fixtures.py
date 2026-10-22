"""nativeReceipt 层次夹具与负控源码（**只写源码，本轮不运行**）。

存在理由
--------
生产代码此前有 5 处按**不存在的顶层字段**消费回执（GAP-1/2）：真实
`directory_receipt.py` 返回 `nativeReceipt.version = 8`、`nativeReceipt.operation = 18`，
`contact/control/after` 与 `moduleBase` 都在 `nativeReceipt` 下，`sourceDirectory`
才是顶层；prepared 的 kind 在**独立的 prepared 文档**里。用自创顶层
`nativeVersion` / `preparedVersion` 的夹具自证，等于用错误消费者证明自己正确。

本模块因此把夹具与负控**固化为源码**：夹具严格照真实 decoder 层次构造；
负控逐条对应 GAP-1..GAP-5，每条都写明**期望的错误码**。运行由统一批次执行，
本文件只提供可被导入的构造器与清单。

用法（统一批次里）
------------------
    from native_receipt_fixtures import (v9_receipt, prepared_v9_doc,
                                         NEGATIVE_CONTROLS, build_negative_case)
    res = assert_v9_consumer(v9_receipt(), "fixture", prepared=prepared_v9_doc())
    for name, case in NEGATIVE_CONTROLS.items():
        decoded, prepared, expect = build_negative_case(name)
        # 期望 assert_v9_consumer / assert_boundary_fields 抛 EntryError(expect)

⚠️ 本文件不访问游戏/队列/桌面；不写任何外部状态；纯内存构造。
"""

from __future__ import annotations

#: 真实 decoder 的常量（`directory_contract.py`：CAPACITY=8192, version=8, operation=18）
NATIVE_RECEIPT_VERSION = 8
NATIVE_RECEIPT_OPERATION = 18
SOURCE_DIRECTORY_CAPACITY = 8192
PREPARED_V9_KIND = "playtest-control-prepared-v9"

#: enumerator 常量（`directory_contract.py:34`：moduleBase + 0x1713e080）
ENUMERATOR_OFFSET = 0x1713E080

#: 一个确定的 moduleBase，供夹具与负控共用（不来自实机，只是构造值）
FIXTURE_MODULE_BASE = 0x7FF600000000


def _control_state(*, global_, level_data, edit_data, cache=None):
    """`nativeReceipt.contact.control.after` 的真实形状。

    `directory_contract.py:33` 用的键是 global / data / cache / cacheEditData；
    `levelData == data == cache` 且 `editData == cacheEditData` 才算同一祖先
    trial/cache。
    """
    cache = level_data if cache is None else cache
    return {"global": global_, "data": level_data, "cache": cache,
            "cacheEditData": edit_data}


def _entity(runtime_id: int, *, editor_guid: int | None,
            belongs: bool | None, spawn_verified: bool | None,
            source_index: int | None, source_instance: dict | None,
            local_avatar: bool = False) -> dict:
    return {
        "runtimeId": runtime_id,
        "localAvatar": local_avatar,
        "editorEntityGuid": editor_guid,
        "belongsToBoundTrial": belongs,
        "targetLevelSpawnMembershipVerified": spawn_verified,
        "sourceDirectoryIndex": source_index,
        "sourceInstance": source_instance,
    }


def v9_receipt(*, runtime_ids=(101, 102), module_base: int | None = FIXTURE_MODULE_BASE,
               global_=0x1122, level_data=0x3344, edit_data=0x5566,
               with_native_receipt: bool = True,
               contact_at_top_level: bool = False,
               leave_top_level_native_version: bool = False) -> dict:
    """按**真实 decoder 层次**构造 v9 `trial-entities` 回执。

    真实层次：
      decoded.operation == 'trial-entities'            （顶层，字符串）
      decoded.sourceDirectoryKnown / sourceDirectory    （顶层）
      decoded.nativeReceipt.version == 8                （嵌套！）
      decoded.nativeReceipt.operation == 18             （嵌套！）
      decoded.nativeReceipt.moduleBase                  （嵌套，可能缺）
      decoded.nativeReceipt.contact.control.after       （嵌套！）

    `with_native_receipt=False` / `contact_at_top_level=True` /
    `leave_top_level_native_version=True` 仅用于**负控**，不用于正控。
    """
    state = _control_state(global_=global_, level_data=level_data, edit_data=edit_data)
    source_directory = {
        "global": global_,
        "levelData": level_data,
        "editData": edit_data,
        "enumerator": (int(module_base) + ENUMERATOR_OFFSET
                       if module_base is not None else FIXTURE_MODULE_BASE + ENUMERATOR_OFFSET),
        # 真实行还带别的键；此处只需被判据用到的
    }
    rows = [
        _entity(rid, editor_guid=0x1000 + i,
                belongs=True, spawn_verified=True,
                source_index=i, source_instance={"record": 0x9000 + i})
        for i, rid in enumerate(runtime_ids)
    ]
    decoded: dict = {
        "operation": "trial-entities",
        "sourceDirectoryKnown": True,
        "sourceDirectory": source_directory,
        "entities": rows,
        # 顶层全页 bool：**只作汇总记录，不得作判据**（GAP-4）
        "targetLevelSpawnMembershipVerified": True,
    }
    if with_native_receipt:
        native_receipt: dict = {
            "version": NATIVE_RECEIPT_VERSION,
            "operation": NATIVE_RECEIPT_OPERATION,
            "contact": {"control": {"after": state}},
        }
        if module_base is not None:
            native_receipt["moduleBase"] = int(module_base)
        decoded["nativeReceipt"] = native_receipt
    if contact_at_top_level:
        # 错误消费者会读这里（真实回执没有）
        decoded["contact"] = {"control": {"after": state}}
    if leave_top_level_native_version:
        # 旧错误消费者的自创字段；真实回执没有
        decoded["nativeVersion"] = NATIVE_RECEIPT_VERSION
        decoded["preparedVersion"] = "prepared-v9"
    return decoded


def prepared_v9_doc(*, kind: str = PREPARED_V9_KIND, session: str = "SESSION.json",
                    target_level_id: int = 1073741843) -> dict:
    """`manifest prepared.json` 的形状（prepared kind 的真实来源）。"""
    return {"kind": kind, "session": session, "targetLevelId": target_level_id}


def _replace_row(decoded: dict, runtime_id: int, **fields) -> dict:
    for e in decoded["entities"]:
        if int(e["runtimeId"]) == int(runtime_id):
            e.update(fields)
            return decoded
    raise KeyError(runtime_id)


def build_negative_case(name: str):
    """返回 `(decoded, prepared, expected_error_code)`；供统一批次逐条断言。

    每条负控都对应一个真实缺口，**期望的错误码写死在返回值里**，
    这样"负控没触发"会直接暴露成断言失败，而不是被静默放过。
    """
    if name == "GAP1_missing_native_receipt":
        return (v9_receipt(with_native_receipt=False), prepared_v9_doc(),
                "V9_CONSUMER_REQUIRED")
    if name == "GAP1_wrong_native_version":
        d = v9_receipt()
        d["nativeReceipt"]["version"] = 7
        return d, prepared_v9_doc(), "V9_CONSUMER_REQUIRED"
    if name == "GAP1_wrong_native_operation":
        d = v9_receipt()
        d["nativeReceipt"]["operation"] = 19
        return d, prepared_v9_doc(), "V9_CONSUMER_REQUIRED"
    if name == "GAP1_wrong_prepared_kind":
        return (v9_receipt(), prepared_v9_doc(kind="playtest-control-prepared-v8"),
                "V9_PREPARED_KIND")
    if name == "GAP1_only_top_level_versions":
        # 旧错误消费者的"自创字段"版本：顶层有 nativeVersion/preparedVersion，
        # 但没有 nativeReceipt ⇒ 必须拒（证明不再被自创字段骗过）
        return (v9_receipt(with_native_receipt=False,
                           leave_top_level_native_version=True),
                prepared_v9_doc(), "V9_CONSUMER_REQUIRED")
    if name == "GAP2_contact_at_top_level_only":
        # 只有顶层 contact、没有 nativeReceipt.contact ⇒ 必须拒（无法核目录绑定）
        d = v9_receipt(contact_at_top_level=True)
        d["nativeReceipt"].pop("contact", None)
        return d, prepared_v9_doc(), "V9_FIELDS_MISSING"
    if name == "GAP2_missing_module_base":
        return (v9_receipt(module_base=None), prepared_v9_doc(),
                "V9_FIELDS_MISSING")
    if name == "GAP2_enumerator_mismatch":
        d = v9_receipt()
        d["sourceDirectory"]["enumerator"] = 12345
        return d, prepared_v9_doc(), "DIRECTORY_ENUMERATOR"
    if name == "GAP2_ancestor_binding_mismatch":
        d = v9_receipt()
        d["nativeReceipt"]["contact"]["control"]["after"]["global"] = 0xDEAD
        return d, prepared_v9_doc(), "DIRECTORY_TRIAL_SOURCE_BINDING"
    if name == "GAP4_whole_page_bool_only":
        # 顶层全页 bool 为 True，但目标行逐行字段缺失 ⇒ 必须拒（不得用全页 bool 替代）
        d = v9_receipt()
        _replace_row(d, 101, targetLevelSpawnMembershipVerified=None)
        return d, prepared_v9_doc(), "V9_FIELDS_MISSING"
    if name == "GAP4_target_belongs_none":
        d = v9_receipt()
        _replace_row(d, 101, belongsToBoundTrial=None)
        return d, prepared_v9_doc(), "V9_FIELDS_MISSING"
    if name == "GAP5_v8_spoofed_as_v9":
        # v8 contact-state 伪造 v9 字段 ⇒ reject_v8_fields_as_v9 必须拒
        d = {"operation": "contact-state",
             "sourceInstance": {"record": 1},
             "entities": [{"runtimeId": 101, "localAvatar": False}]}
        return d, None, "V8_FIELDS_SPOOFED_AS_V9"
    raise KeyError(name)


#: 负控清单（名称 → 说明）。统一批次按此逐条跑并断言错误码。
NEGATIVE_CONTROLS = {
    "GAP1_missing_native_receipt": "缺 nativeReceipt 整块",
    "GAP1_wrong_native_version": "nativeReceipt.version != 8",
    "GAP1_wrong_native_operation": "nativeReceipt.operation != 18",
    "GAP1_wrong_prepared_kind": "prepared.kind 不是 playtest-control-prepared-v9",
    "GAP1_only_top_level_versions": "只有自创顶层 nativeVersion/preparedVersion",
    "GAP2_contact_at_top_level_only": "contact 只在顶层、nativeReceipt 下缺失",
    "GAP2_missing_module_base": "缺 moduleBase（无法核 enumerator）",
    "GAP2_enumerator_mismatch": "enumerator != moduleBase + 0x1713e080",
    "GAP2_ancestor_binding_mismatch": "目录侧与 contact 控制流祖先不一致",
    "GAP4_whole_page_bool_only": "顶层全页 bool 为真但目标行字段缺失",
    "GAP4_target_belongs_none": "目标行 belongsToBoundTrial 为 None",
    "GAP5_v8_spoofed_as_v9": "v8 contact-state 伪造 v9 专属字段",
}

#: 正控（必须不报错）：真实层次夹具 + 真实 prepared kind
POSITIVE_CONTROLS = {
    "v9_receipt_real_hierarchy": "按真实 decoder 层次构造的 v9 回执",
    "v9_receipt_with_prepared": "同上 + kind=playtest-control-prepared-v9",
}
