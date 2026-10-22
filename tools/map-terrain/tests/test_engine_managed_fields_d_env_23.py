"""D-ENV-23 回归：engine-managed 根字段（field6/46）语义分类，内容域必须仍逐字节 FAIL。

背景：真实地形 save 后仅 field7（内容，按计划）、field6（目录/页签 40→41 条，1439→1474B）、
field46（存档历史头 1→2 条，22→44B）变化；实体表 field5 / 定义 field15 等逐字节相同。
旧实现把 field6 当 ``UNRELATED_LEVEL_FIELDS_CHANGED`` 误报 FAIL。

新语义（不放宽）：
* field6 目录形态（≥20 条记录、有界、记录数变化 ≤2）⇒ ok=True，classification=engine-managed，
  且记录 before/after sha 与字节差；
* 小规模 field6（如实体目录的少量记录变化）⇒ 仍 FAIL；
* 内容域/未知根字段（如 field10）变化 ⇒ FAIL；
* 形态异常（记录数不足/不可解析）⇒ FAIL。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import terrain_model  # noqa: E402
from gil_container import Container, Field, decode_container, encode_container, encode_fields, parse_fields  # noqa: E402
import test_terrain_model as fixtures  # noqa: E402


def with_roots(blob, changed=None):
    """同 test_save_proof.py::with_roots（合成根字段 5/6/10，各 1 条 varint 记录）。"""
    container = decode_container(blob)
    fields = parse_fields(container.payload)
    for number in (5, 6, 10):
        fields.append(Field(number, 2, data=encode_fields(
            [Field(1, 0, value=number + (1 if number == changed else 0))])))
    return encode_container(Container(container.subtype, encode_fields(fields)))


def with_directory6(blob, record_count):
    """真实 field6 观测形态：40 条目录记录（每条 ~36B，length-delimited）。"""
    container = decode_container(blob)
    fields = parse_fields(container.payload)
    records = [Field(1, 2, data=(f"tab-{i:03d}-".encode() + b"x" * 28))
               for i in range(record_count)]
    fields.append(Field(6, 2, data=encode_fields(records)))
    return encode_container(Container(container.subtype, encode_fields(fields)))


def terrain_id_of(blob) -> int:
    return terrain_model.decode_save(blob)["terrains"][0]["terrainId"]


def expected_cells(blob, terrain_id):
    model = terrain_model.decode_save(blob)
    return terrain_model.select(model, terrain_id)["cells"]


class EngineManagedFieldTests(unittest.TestCase):
    def test_field6_directory_change_classified_engine_managed(self):
        before = with_directory6(fixtures.save([fixtures.cell(1, 2, 1)]), 40)
        after = with_directory6(fixtures.save([fixtures.cell(1, 2, 1)]), 41)
        tid = terrain_id_of(before)
        result = terrain_model.verify_expected_save(
            before, after, tid, expected_cells(after, tid), set())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["failures"], [])
        self.assertIn(6, result["engineManagedFields"])
        record = [c for c in result["fieldClassifications"] if c["rootField"] == 6][0]
        self.assertEqual(record["classification"], "engine-managed")
        self.assertFalse(record["semanticsVerified"])  # 语义仍未分类，只是允许的有界差异
        self.assertIsNotNone(record["beforeSha256"])
        self.assertIsNotNone(record["afterSha256"])
        self.assertTrue(result["contentDomainsByteIdentical"])

    def test_small_field6_change_still_fails(self):
        # 旧合成夹具的 1 条记录形态（历史 test_entity_directory_and_graph_root_changes_rejected）
        before = with_roots(fixtures.save([fixtures.cell(1, 2, 1)]))
        after = with_roots(fixtures.save([fixtures.cell(1, 2, 1)]), changed=6)
        tid = terrain_id_of(before)
        result = terrain_model.verify_expected_save(
            before, after, tid, expected_cells(after, tid), set())
        self.assertFalse(result["ok"], result)
        self.assertIn("UNRELATED_LEVEL_FIELDS_CHANGED", result["failures"])

    def test_content_root_field_change_still_fails(self):
        before = with_roots(fixtures.save([fixtures.cell(1, 2, 1)]))
        after = with_roots(fixtures.save([fixtures.cell(1, 2, 1)]), changed=10)
        tid = terrain_id_of(before)
        result = terrain_model.verify_expected_save(
            before, after, tid, expected_cells(after, tid), set())
        self.assertFalse(result["ok"], result)
        self.assertIn("UNRELATED_LEVEL_FIELDS_CHANGED", result["failures"])
        self.assertFalse(result["contentDomainsByteIdentical"])
        record = [c for c in result["fieldClassifications"] if c["rootField"] == 10][0]
        self.assertEqual(record["classification"], "unknown")

    def test_malformed_field6_change_still_fails(self):
        before = with_directory6(fixtures.save([fixtures.cell(1, 2, 1)]), 40)
        after = with_directory6(fixtures.save([fixtures.cell(1, 2, 1)]), 40)
        # 把 after 的 root6 换成不可解析字节（仍 wire-2 外层，但 inner 非合法字段流）
        container = decode_container(after)
        fields = parse_fields(container.payload)
        for index, field in enumerate(fields):
            if field.number == 6:
                fields[index] = Field(6, 2, data=b"\xff\xff\xff")
        malformed = encode_container(Container(container.subtype, encode_fields(fields)))
        tid = terrain_id_of(before)
        result = terrain_model.verify_expected_save(
            before, malformed, tid, expected_cells(malformed, tid), set())
        self.assertFalse(result["ok"], result)
        self.assertIn("UNRELATED_LEVEL_FIELDS_CHANGED", result["failures"])


class RealDEnv23FixtureTests(unittest.TestCase):
    """env-verify 冻结的真实 before/after 一对 .gil（D-ENV-23 回归夹具）。"""

    DIR = HERE.parents[1] / ".runtime/env-verify/fixtures/d-env-23"
    BEFORE = DIR / "T0-before-16156.gil"
    AFTER = DIR / "T1-after-16357.gil"
    MANIFEST = DIR / "MANIFEST.json"

    def setUp(self):
        if not (self.BEFORE.is_file() and self.AFTER.is_file()):
            self.skipTest(f"real D-ENV-23 fixture not present: {self.DIR}")

    def test_manifest_matches_frozen_bytes(self):
        manifest = __import__("json").loads(self.MANIFEST.read_text(encoding="utf-8-sig"))
        files = {item["file"].replace("\\", "/").split("/")[-1]: item for item in manifest["files"]}
        self.assertEqual(files["T0-before-16156.gil"]["sha256"], terrain_model.digest(self.BEFORE.read_bytes()))
        self.assertEqual(files["T1-after-16357.gil"]["sha256"], terrain_model.digest(self.AFTER.read_bytes()))
        self.assertEqual(files["T0-before-16156.gil"]["bytes"], len(self.BEFORE.read_bytes()))
        self.assertEqual(files["T1-after-16357.gil"]["bytes"], len(self.AFTER.read_bytes()))
        self.assertEqual(manifest["schema"], "env-verify-d-env-23-fixture/v1")
        self.assertEqual(manifest["knownSemantics"]["field46"], "save-history header: 1 -> 2 records (new head prepended, old retained)")

    def test_real_save_passes_with_engine_managed_delta(self):
        before, after = self.BEFORE.read_bytes(), self.AFTER.read_bytes()
        model_before, model_after = terrain_model.decode_save(before), terrain_model.decode_save(after)
        tid = model_before["terrains"][0]["terrainId"]
        target_after = terrain_model.select(model_after, tid)
        changed = {key for key in target_after["rawCells"]
                   if terrain_model.select(model_before, tid)["rawCells"].get(key) != target_after["rawCells"][key]}
        result = terrain_model.verify_expected_save(before, after, tid, target_after["cells"], changed)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["failures"], [])
        self.assertTrue(result["contentDomainsByteIdentical"], result)
        self.assertTrue(result["engineManagedChangesAllowed"], result)
        fields = {c["rootField"]: c for c in result["fieldClassifications"]}
        self.assertEqual(fields[46]["classification"], "engine-managed-history", fields.get(46))
        self.assertEqual((fields[46]["beforeRecordCount"], fields[46]["afterRecordCount"]), (1, 2), fields[46])
        self.assertEqual(fields[6]["classification"], "engine-managed", fields.get(6))
        self.assertEqual(fields[6]["byteDelta"], 35, fields[6])
        self.assertIn(46, result["engineManagedFields"])
        self.assertIn(6, result["engineManagedFields"])
        # 内容域：field5 实体表 / field15 定义 等根字段不得出现在变化列表
        self.assertEqual(set(result["changedTopLevelFields"]), {"6", "46"}, result["changedTopLevelFields"])


if __name__ == "__main__":
    unittest.main()
