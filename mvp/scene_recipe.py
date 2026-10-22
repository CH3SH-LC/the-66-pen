"""A bounded six-entity scene recipe; never generates GIA or accesses the game."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE_VERSION = 'six-platforms/1'


class RecipeError(ValueError):
    pass


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecipeError(f'{label} must be a finite number')
    try:
        result = float(value)
    except OverflowError as exc:
        raise RecipeError(f'{label} must be finite') from exc
    if not math.isfinite(result):
        raise RecipeError(f'{label} must be finite')
    return result


def _within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RecipeError('path escapes project')
    return resolved


def create_candidate(horizontal_gap, vertical_step):
    root = ROOT.resolve()
    baseline = _within(root / 'mvp/scene.json', root)
    raw = baseline.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    scene = json.loads(raw)
    gap = _number(horizontal_gap, 'horizontal_gap')
    step = _number(vertical_step, 'vertical_step')
    bounds = scene['constraints']
    if not (bounds['horizontal_gap_min'] <= gap <= bounds['horizontal_gap_max']):
        raise RecipeError('horizontal_gap outside baseline design constraints')
    if not (bounds['step_up_min'] <= step <= bounds['step_up_max']):
        raise RecipeError('vertical_step outside baseline design constraints')
    entities = scene['entities']
    if len(entities) != 6 or len(scene['templates']) != 5:
        raise RecipeError('recipe requires the existing five-template six-entity baseline')
    if [e['index'] for e in entities] != list(range(6)) or entities[0]['position'] != [0, 0, 0]:
        raise RecipeError('recipe requires ordered baseline indices and origin start')

    def size(entity, axis):
        nominal = _number(scene['templates'][str(entity['template_id'])]['size_units'], 'size_units')
        scale = _number(entity['scale'][axis], 'scale')
        if nominal <= 0 or scale <= 0:
            raise RecipeError('nominal dimensions must be positive')
        return nominal * scale

    x = 0.0
    for i, entity in enumerate(entities):
        if i:
            x += size(entities[i-1], 0) / 2 + gap + size(entity, 0) / 2
        entity['position'][0] = round(x, 12)
        entity['position'][1] = round(i * step, 12)
    goal_y = round(entities[-1]['position'][1] + size(entities[-1], 1) / 2, 12)
    scene['scene_id'] = f'platformer-recipe-gap-{gap:g}-step-{step:g}-unmeasured'
    scene['title'] = f'六实体配方候选：间隙{gap:g}，步长{step:g}（未实测）'
    scene['layout_intent'].update(horizontal_edge_gap=gap, vertical_step=step,
                                  start_surface_y=size(entities[0], 1)/2, goal_surface_y=goal_y)
    scene['coordinate_system']['unit'] = '名义设计单位：模板size_units与scale相乘估计尺寸，实际边界/碰撞尚未实测'
    scene['goal_rule'] = f'设计意图：到达终点顶面（名义 y={goal_y:g}）；未绑定游戏结算，未验证通关。'
    entities[-1]['comment'] = f'终点，名义顶面 y={goal_y:g}；胜利条件与实际碰撞待绑定和验收。'
    scene['recipe'] = {'recipeVersion': RECIPE_VERSION, 'sourceBaselineSha256': source_hash,
                       'parameters': {'horizontal_gap': gap, 'vertical_step': step},
                       'runtimeVerified': False, 'materialEffect': None, 'collision': None,
                       'physics': None, 'boundsMeaning': 'project design constraints, not measured jump ability'}
    content = (json.dumps(scene, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    content_hash = hashlib.sha256(content).hexdigest()
    directory = _within(root / 'mvp/candidates', root)
    directory.mkdir(parents=True, exist_ok=True)
    target = _within(directory / f'recipe-{content_hash}.json', root)
    if baseline.read_bytes() != raw:
        raise RecipeError('baseline changed while preparing candidate')
    try:
        with target.open('xb') as stream:
            stream.write(content)
        reused = False
    except FileExistsError:
        if target.read_bytes() != content:
            raise RecipeError('candidate path contains different bytes; refusing overwrite')
        reused = True
    if baseline.read_bytes() != raw:
        raise RecipeError('baseline changed during candidate creation; inspect source before build')
    return {'scene': f'candidates/{target.name}', 'sha256': content_hash, 'reused': reused,
            'recipeVersion': RECIPE_VERSION, 'sourceBaselineSha256': source_hash,
            'entityCount': 6, 'templateCount': 5, 'runtimeVerified': False,
            'gameAccepted': 'unknown', 'artifactKind': 'internal-scene-json'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gap', type=float, required=True)
    parser.add_argument('--step', type=float, required=True)
    args = parser.parse_args()
    try:
        result = create_candidate(args.gap, args.step)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': {'code': 'RECIPE_FAILED', 'message': str(exc)}}, ensure_ascii=True))
        return 1
    print(json.dumps({'ok': True, **result}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
