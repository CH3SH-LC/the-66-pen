"""Read-only interface inventory. Never imports execution backends or contacts the game."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name('interface_inventory.json')


def literal_sets(path):
    values = {}
    def read(node):
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return set(read(node.left)) | set(read(node.right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'frozenset' and len(node.args) == 1 and not node.keywords:
            return set(read(node.args[0]))
        return ast.literal_eval(node)
    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = read(node.value)
            except (KeyError, ValueError, TypeError, SyntaxError):
                pass
    # None means no literal allowlist. It is not an empty supported-template set.
    return sorted(values['TEMPLATES']) if 'TEMPLATES' in values else None


def inventory(profile='all', gaps=False):
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    entries = data['capabilities']
    if len({r['id'] for r in entries}) != len(entries):
        raise ValueError('Duplicate inventory ID')
    for row in entries:
        path = (ROOT / row['source']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Source outside project')
        exists = path.is_file()
        raw = path.read_bytes() if exists else b''
        row['sourceCheck'] = {
            'exists': exists,
            'anchorPresent': (row['needle'] in raw.decode('utf-8-sig')) if exists and row['needle'] else None,
            'sha256': hashlib.sha256(raw).hexdigest() if exists else None,
        }
    # 2026-10-09: both literal template sets went with the whitelist; this now reports their
    # removal instead of comparing two empty sets as though they agreed.
    front = literal_sets(ROOT / 'tools/authoring/author.py')
    native = literal_sets(ROOT / 'tools/game-executor/build_scene_profile.py')
    source = (ROOT / 'tools/game-executor/scene_cli.py').read_text(encoding='utf-8-sig')
    catalog = (ROOT / 'tools/editor-bridge/Adapter/SceneCatalog.cs').read_text(encoding='utf-8-sig')
    findings = [
        dict(id='template-wrapper-drift', unifiedTemplateIds=front, backendTemplateIds=native,
             missingFromUnified=sorted(set(native)-set(front)) if front is not None and native is not None else None,
             literalAllowlistsAbsent=front is None and native is None,
             meaning='No literal allowlist is not proof of all templates. Current create validation uses a nonzero uint32 id; native placement remains separately verified.'),
        dict(id='batch-wrapper-drift', backendHasBatch="'create-batch'" in source,
             unifiedHasBatch='create-batch' in (ROOT / 'tools/authoring/author.py').read_text(encoding='utf-8-sig')),
        dict(id='scene-catalog-limit', limit=int(re.search(r'SceneEntityLimit\s*=\s*(\d+)', catalog).group(1)),
             meaning='catalog.scene child array limit; not a game entity limit'),
    ]
    selected = [r for r in entries if (profile == 'all' or r['profile'] == profile)
                and (not gaps or r['status'] != 'bounded')]
    data.update(capabilities=selected, findings=findings,
                counts=dict(Counter(r['status'] for r in selected)),
                sourceChecksPassed=all(r['sourceCheck']['exists'] and r['sourceCheck']['anchorPresent'] is not False for r in entries),
                liveProbed=False, historicalEvidenceRevalidated=False,
                warning='Source anchors and hashes detect drift only; they do not prove behavior or runtime acceptance.')
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', choices=('all','core','optional'), default='all')
    ap.add_argument('--gaps', action='store_true', help='Include backend, partial, research and missing entries')
    ap.add_argument('--format', choices=('json','markdown'), default='json')
    args = ap.parse_args()
    try:
        report = inventory(args.profile, args.gaps)
        if args.format == 'markdown':
            lines = ['# 完整游戏接口盘点', '', report['scope'], '',
                     '范围：core 是可开始、可通关/失败、可重试、有反馈且可保存验收的基础游戏；optional 按战斗、多人、道具等玩法选用。不是所有游戏必须调用所有接口。', '',
                     '状态：' + '；'.join(k + '=' + v for k,v in report['statuses'].items()), '',
                     '本表ID是规划键；只有“现有入口”栏列出的才有对应实现，仍须遵守限制。源码锚点检查不等于当前运行验证。', '',
                     '|优先级|规划ID / 能力|范围|状态|现有入口|缺口与边界|源码或证据入口|',
                     '|---|---|---|---|---|---|---|']
            for r in report['capabilities']:
                lines.append('|'+ '|'.join(str(x).replace('|','/') for x in (r['priority'],r['id']+' / '+r['title'],r['profile'],r['status'],r['entry'] or '尚无完整入口',r['gap'],r['source']))+'|')
            lines += ['', '## 自动检查结果', '', '```json', json.dumps(report['findings'],ensure_ascii=False,indent=2), '```', '',
                      '来源锚点全部匹配：'+str(report['sourceChecksPassed'])+'。仅检测文件与锚点；不证明其中语义、函数行为和历史验收仍适用于当前版本。']
            print('\n'.join(lines))
        else:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report['sourceChecksPassed'] else 2
    except (ValueError, OSError, KeyError, AttributeError) as error:
        print(json.dumps(dict(ok=False, error=str(error), liveProbed=False), ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
