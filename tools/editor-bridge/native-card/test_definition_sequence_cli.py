"""definition_sequence_cli 的离线契约测试（不触游戏、不写操作目录）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "tools/editor-bridge/native-card/definition_sequence_cli.py"
LIFE_PLAN = ROOT / "data/m2/life/window/w3/definition-sequence-plan-w3b.json"


def make_inputs(tmp_path: Path):
    target = tmp_path / "1844.gil"
    target.write_bytes(b"synthetic-gil-bytes")
    backup = tmp_path / "1844.backup.gil"
    backup.write_bytes(target.read_bytes())
    session = tmp_path / "session.json"
    session.write_text("{}", encoding="utf-8")
    queue = tmp_path / "queue"
    queue.mkdir(exist_ok=True)
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps({"template-item": "a" * 64, "template-currency": "b" * 64}), encoding="utf-8")
    return target, backup, session, queue, reviewed


def run(*args):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", str(CLI), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))


def base_args(tmp_path, *, level="1073741844", plan=None):
    target, backup, session, queue, reviewed = make_inputs(tmp_path)
    return ["--plan", str(plan or LIFE_PLAN), "--level-id", level,
            "--operation-id", "pytest-life-w3b", "--session", str(session),
            "--target-gil", str(target), "--backup", str(backup), "--queue", str(queue),
            "--reviewed-source-sets", str(reviewed), "--validate-only"]


def test_validate_only_life_plan_1844_ok(tmp_path):
    proc = run(*base_args(tmp_path), "--authorization-source", "lead-authorized-20261022-life-w3b")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True and payload["validateOnly"] is True
    assert payload["levelId"] == 1073741844
    assert len(payload["definitions"]) == 4
    assert payload["kinds"] == ["currency", "item"]


def test_validate_1844_requires_authorization_source(tmp_path):
    proc = run(*base_args(tmp_path))
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["code"] == "VALIDATION_FAILED"
    assert "LEVEL_AUTHORIZATION_SOURCE_REQUIRED" in proc.stdout


def test_validate_unknown_level_rejected(tmp_path):
    proc = run(*base_args(tmp_path, level="1073741845"), "--authorization-source", "x" * 12)
    assert proc.returncode == 2
    # 计划本身是 1844，但 --level-id 不在白名单 → 级别不匹配/未授权二选一
    assert ("DEFINITION_PLAN_LEVEL_MISMATCH" in proc.stdout
            or "ONLY_AUTHORIZED_LEVEL_1843_OR_1844" in proc.stdout)


def test_validate_plan_level_mismatch(tmp_path):
    plan = json.loads(LIFE_PLAN.read_text(encoding="utf-8-sig"))
    plan["levelId"] = 1073741843
    bad = tmp_path / "bad-plan.json"
    bad.write_text(json.dumps(plan), encoding="utf-8")
    proc = run(*base_args(tmp_path, plan=bad), "--authorization-source", "lead-authorized-20261022-life-w3b")
    assert proc.returncode == 2
    assert "DEFINITION_PLAN_LEVEL_MISMATCH" in proc.stdout


def test_validate_reviewed_source_sets_required(tmp_path):
    args = base_args(tmp_path)
    # point reviewed-source-sets at a file with wrong tool keys
    _, _, _, _, reviewed = make_inputs(tmp_path)
    reviewed.write_text(json.dumps({"template-item": "a" * 64}), encoding="utf-8")
    args = [str(a) for a in args]
    idx = args.index("--reviewed-source-sets")
    args[idx + 1] = str(reviewed)
    proc = run(*args, "--authorization-source", "lead-authorized-20261022-life-w3b")
    assert proc.returncode == 2
    assert "REVIEWED_SOURCE_SETS_REQUIRED" in proc.stdout


def test_validate_backup_must_match_target(tmp_path):
    args = base_args(tmp_path)
    idx = args.index("--backup")
    Path(args[idx + 1]).write_bytes(b"different bytes")
    proc = run(*args, "--authorization-source", "lead-authorized-20261022-life-w3b")
    assert proc.returncode == 2
    assert "BACKUP_BYTES_CHANGED" in proc.stdout
