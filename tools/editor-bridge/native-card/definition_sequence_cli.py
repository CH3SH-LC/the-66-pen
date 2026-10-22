#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""definition_sequence.py 的 CLI 封装（life W3-B / env 窗口用）。

固定串行链：request → review → build → dispatch → accept，只注册 catalog（不 save）。
本 CLI 只做三件事：① 参数/plan/来源集白名单校验（把带元数据的 plan 收敛到模块严格 schema）；
② 通过 scene_cli 提供 fresh_baseline 回调；③ 调 register() 并把结果写到 --out。

用法：
  python -B -X utf8 tools/editor-bridge/native-card/definition_sequence_cli.py \
    --plan data/m2/life/window/w3/definition-sequence-plan-w3b.json \
    --level-id 1073741844 --operation-id life-w3b-definitions \
    --session .runtime/game-executor/current-native-session.json \
    --target-gil <1844 正式 .gil> --backup <同字节 backup> \
    --queue .runtime/editor-bridge/elevated-queue \
    --reviewed-source-sets <reviewed-sources.json> \
    --authorization-source "lead-authorized-20261022-life-w3b" \
    --out .runtime/toolchain/life-w3b/registered.json

只校验（离线，不触游戏）：追加 --validate-only

退出码：0 成功/校验通过；2 参数或校验失败；3 注册链失败（result.json 仍写入 run 目录）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import definition_sequence as sequence  # noqa: E402

SCENE_CLI = ROOT / 'tools/game-executor/scene_cli.py'
OPERATION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}')
PLAN_REQUIRED = {'schemaVersion', 'levelId', 'definitions'}
ROW_REQUIRED = {'key', 'kind', 'name'}


def fail(code: str, message: str, **extra) -> int:
    print(json.dumps(dict({'ok': False, 'code': code, 'error': message}, **extra), ensure_ascii=False))
    return 2


def load_json(path: Path, code: str):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise sequence.SequenceError(code + ':FILE_NOT_FOUND') from None
    except ValueError as exc:
        raise sequence.SequenceError(code + ':INVALID_JSON') from exc


def canonical_plan(document) -> tuple[dict, dict]:
    """把带元数据的 plan 收敛到模块严格 schema（{schemaVersion,levelId,definitions:[{key,kind,name}]}）。

    life 的 plan 额外带 batchId/writer/source1843 等说明字段；模块 validate_plan 只接受三个顶层键
    和 {key,kind,name} 行。这里只剔除非语义字段并记录 ignored 清单，不改变任何语义值。
    """
    if not isinstance(document, dict) or not PLAN_REQUIRED <= set(document):
        raise sequence.SequenceError('DEFINITION_PLAN_FIELDS')
    rows, ignored_rows = [], {}
    for index, row in enumerate(document.get('definitions') or []):
        if not isinstance(row, dict) or not ROW_REQUIRED <= set(row):
            raise sequence.SequenceError('DEFINITION_ROW_FIELDS')
        rows.append({key: row[key] for key in ROW_REQUIRED})
        extra = sorted(set(row) - ROW_REQUIRED)
        if extra:
            ignored_rows[index] = extra
    canonical = {'schemaVersion': document['schemaVersion'], 'levelId': document['levelId'],
                 'definitions': rows}
    audit = {'ignoredTopLevelKeys': sorted(set(document) - PLAN_REQUIRED),
             'ignoredRowFields': ignored_rows, 'sourcePlanSha256': None}
    return canonical, audit


def read_reviewed(path: Path) -> dict:
    doc = load_json(path, 'REVIEWED_SOURCE_SETS')
    if not isinstance(doc, dict):
        raise sequence.SequenceError('REVIEWED_SOURCE_SETS_NOT_OBJECT')
    if set(doc) == {'sources'} and isinstance(doc['sources'], dict):
        doc = doc['sources']
    return doc


def validate(args) -> dict:
    plan_path = Path(args.plan)
    plan, audit = canonical_plan(load_json(plan_path, 'PLAN'))
    audit['sourcePlanSha256'] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    level = sequence.validate_plan(plan, expected_level=args.level_id)['levelId']
    if not OPERATION_ID.fullmatch(args.operation_id):
        raise sequence.SequenceError('OPERATION_ID')
    if level != sequence.LEVEL and not (args.authorization_source or '').strip():
        raise sequence.SequenceError('LEVEL_AUTHORIZATION_SOURCE_REQUIRED')
    session = Path(args.session)
    target = Path(args.target_gil)
    backup = Path(args.backup)
    queue = Path(args.queue)
    if not session.is_file():
        raise sequence.SequenceError('SESSION_FILE_MISSING')
    if not target.is_file():
        raise sequence.SequenceError('TARGET_GIL_MISSING')
    if not backup.is_file():
        raise sequence.SequenceError('BACKUP_MISSING')
    if sequence.sha(target) != sequence.sha(backup):
        raise sequence.SequenceError('BACKUP_BYTES_CHANGED')
    if not queue.is_dir():
        raise sequence.SequenceError('QUEUE_DIR_MISSING')
    reviewed = read_reviewed(Path(args.reviewed_source_sets))
    needed = {sequence.TOOLS[row['kind']][0] for row in plan['definitions']}
    if set(reviewed) != needed:
        raise sequence.SequenceError('REVIEWED_SOURCE_SETS_REQUIRED')
    if not all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in reviewed.values()):
        raise sequence.SequenceError('REVIEWED_SOURCE_SETS_REQUIRED')
    return {
        'ok': True,
        'plan': str(plan_path),
        'planSha256': audit['sourcePlanSha256'],
        'canonicalPlanSha256': hashlib.sha256(
            json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'levelId': level,
        'definitions': [row['key'] for row in plan['definitions']],
        'kinds': sorted({row['kind'] for row in plan['definitions']}),
        'reviewedTools': sorted(reviewed),
        'targetSha256': sequence.sha(target),
        'sessionSha256': sequence.sha(session),
        'authorizationSource': args.authorization_source,
        'planAudit': audit,
    }


def make_baseline(args):
    def fresh(key: str) -> dict:
        argv = [sys.executable, '-B', '-X', 'utf8', str(SCENE_CLI), 'inspect',
                '--level-id', str(args.level_id), '--session', args.session,
                '--elevated-queue', args.queue]
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=args.baseline_timeout)
        try:
            reply = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise sequence.SequenceError('FRESH_BASELINE_NO_JSON:' + proc.stdout.strip()[-300:]) from None
        if proc.returncode != 0 or reply.get('ok') is not True or not reply.get('run'):
            raise sequence.SequenceError('FRESH_BASELINE_FAILED:' + str(reply.get('error'))[:300])
        return {'ok': True, 'run': reply['run'], 'key': key, 'stdoutBytes': len(proc.stdout)}
    return fresh


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--level-id', type=int, required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--target-gil', required=True)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--queue', required=True)
    parser.add_argument('--reviewed-source-sets', required=True)
    parser.add_argument('--authorization-source', default=None,
                        help='非 1843 级别必填：lead/owner 授权来源字符串（记录进 operation.json）')
    parser.add_argument('--validate-only', action='store_true', help='只做离线校验，不写操作目录、不触游戏')
    parser.add_argument('--baseline-timeout', type=int, default=240)
    parser.add_argument('--out', default=None, help='registered.json 输出路径；同目录写 audit.json')
    args = parser.parse_args(argv)
    try:
        summary = validate(args)
    except sequence.SequenceError as exc:
        return fail('VALIDATION_FAILED', str(exc))
    if args.validate_only:
        print(json.dumps(dict(summary, validateOnly=True), ensure_ascii=False))
        return 0
    try:
        canonical, audit = canonical_plan(load_json(Path(args.plan), 'PLAN'))
        audit['sourcePlanSha256'] = hashlib.sha256(Path(args.plan).read_bytes()).hexdigest()
        result = sequence.register(
            canonical,
            operation_id=args.operation_id,
            session_file=args.session,
            target_gil=args.target_gil,
            backup=args.backup,
            queue=args.queue,
            reviewed_source_sets=read_reviewed(Path(args.reviewed_source_sets)),
            fresh_baseline=make_baseline(args),
            level_id=args.level_id,
            authorization_source=args.authorization_source,
        )
    except sequence.SequenceError as exc:
        return fail('SEQUENCE_REJECTED', str(exc))
    except Exception as exc:  # noqa: BLE001 - 链内异常按失败返回，不重放
        return fail('SEQUENCE_ERROR', f'{type(exc).__name__}: {exc}')
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        out.with_name('audit.json').write_text(
            json.dumps(dict(audit, levelId=result.get('levelId'), operationId=args.operation_id),
                       ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') is True else 3


if __name__ == '__main__':
    raise SystemExit(main())
