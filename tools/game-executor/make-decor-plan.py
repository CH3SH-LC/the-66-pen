"""Build the decoration plan for the MVP course. Pure arithmetic, no game access.

Everything here is generated from a few named parameters so a correction round is a
one-line change and a regeneration, not a hand edit of two hundred rows.

What is known and what is not
-----------------------------
Positions are computed. SIZES ARE NOT: only 20001034/20001875/20001224 have a size that
was read back out of a real save, and none of the decoration templates do. So the layout
keeps every decoration outside the jumping corridor (|z| >= 2.6 against a corridor that
is at most 6 wide) and puts a single `groundY` in charge of how high the whole set sits,
which is the number most likely to need one correction after the first look.

Usage:
  python tools/game-executor/make-decor-plan.py [--out plan.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Template ids, all from the editor's own prefab registry with the library icon inspected
# before selection (see docs/gameplay/MVP-DECORATION-20260923.md).
TREE, BUSH, LAMP, TORCH, FLAG, ROCK, STONE_PILE, FENCE = (
    20001001, 20001004, 20001014, 20001055, 20001017, 20001042, 20001007, 20001047)

# The course runs from P0 at x=0 to P5 at x=17, centred on z=0.
X_MIN, X_MAX = -10.0, 28.0
GROUND_Y = 0.0          # the one number to correct if the set sits wrong
FLAG_X, FLAG_Z = -4.0, 0.0


def span(start: float, stop: float, step: float, side: float, y: float, template: int,
         tag: str) -> list[dict]:
    out = []
    x = start
    index = 0
    while x <= stop + 1e-9:
        out.append({'label': f'{tag}_{index}', 'template_id': template,
                    'position': [round(x, 4), y, round(side, 4)], 'scale': [1.0, 1.0, 1.0]})
        x += step
        index += 1
    return out


def build() -> list[dict]:
    placements: list[dict] = []
    # Fence line: the closest thing to the corridor, so it reads as its edge. Both sides.
    for side in (-1, 1):
        placements += span(X_MIN + 4, X_MAX - 3, 1.2, side * 3.4, GROUND_Y, FENCE, f'fence{"L" if side < 0 else "R"}')
    # Light: lamps on one side, torches on the other, so the run has rhythm rather than
    # two identical rows. This is the corridor's edge light, the strongest visual change.
    placements += span(X_MIN + 6, X_MAX - 6, 3.0, -2.6, GROUND_Y, LAMP, 'lamp')
    placements += span(X_MIN + 6, X_MAX - 6, 3.0, 2.6, GROUND_Y, TORCH, 'torch')
    # Understory, then rock, then tree, stepping outward and getting taller.
    for side in (-1, 1):
        s = 'L' if side < 0 else 'R'
        placements += span(X_MIN + 4, X_MAX - 4, 1.8, side * 4.6, GROUND_Y, BUSH, f'bush{s}')
        placements += span(X_MIN + 2, X_MAX - 2, 2.5, side * 6.0, GROUND_Y, ROCK, f'rock{s}')
        placements += span(X_MIN, X_MAX, 3.0, side * 7.8, GROUND_Y, TREE, f'tree{s}')
        placements += span(X_MIN + 2, X_MAX - 2, 4.0, side * 10.6, GROUND_Y, TREE, f'treeFar{s}')
        placements += span(X_MIN + 3, X_MAX - 3, 4.5, side * 9.2, GROUND_Y, STONE_PILE, f'pile{s}')
    # A second, sparser bush row just outside the fence line to break the straight edge.
    for side in (-1, 1):
        placements += span(X_MIN + 8, X_MAX - 8, 6.0, side * 3.0, GROUND_Y, BUSH,
                           f'bushIn{"L" if side < 0 else "R"}')
    # Gateposts: one pair behind the start, one pair behind the goal.
    for dx, where in ((-2.5, 'start'), (2.5, 'goal')):
        for side in (-1, 1):
            placements.append({'label': f'flag_{where}_{"L" if side < 0 else "R"}',
                               'template_id': FLAG,
                               'position': [FLAG_X + (0.0 if where == 'start' else 23.0),
                                            GROUND_Y, side * 3.0],
                               'scale': [1.0, 1.0, 1.0]})
    return placements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    placements = build()
    plan = {
        '_note': 'MVP 关卡装饰计划（生成物，勿手改；改 make-decor-plan.py 后重跑）',
        '_generator': 'tools/game-executor/make-decor-plan.py',
        '_sizes_unknown': '除 20001034/20001875/20001224 外，本例所有模板的实际尺寸均未验证。'
                          '布局据此选择：全部放在跳跃走廊之外（|z| >= 2.6），并由 groundY 统管整体高度。',
        '_correction': '若整体偏高/偏低，只需改 groundY 重跑；若某一类元件明显不对，改 span 的 side。',
        'step': 'MW_MVP_Decor200',
        'groundY': GROUND_Y,
        'placements': placements,
    }
    text = json.dumps(plan, ensure_ascii=False, indent=1) + '\n'
    if args.out:
        args.out.write_text(text, encoding='utf-8')
        kinds: dict[int, int] = {}
        for item in placements:
            kinds[item['template_id']] = kinds.get(item['template_id'], 0) + 1
        print(json.dumps({'out': str(args.out), 'placements': len(placements),
                          'byTemplate': {str(k): v for k, v in sorted(kinds.items())}}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
