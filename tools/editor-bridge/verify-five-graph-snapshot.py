#!/usr/bin/env python3
"""Independently verify a five-graph level snapshot (.gil) — the demo baseline.

Reuses the four-graph verifier as a library (the same way verify-finish-graph.py reuses
verify-runtime-audit.py) so the tile geometry, template mix and start-edge helpers are
literally the checked ones, not a second copy that could drift.

What is new here is the fifth graph. This snapshot is the first time the demo graph
MW_Game_Loop_20260917 has been checked as *persisted content* rather than as an in-memory
model or an export: it must appear in the save with 29 nodes and be bound alongside the
other four.

Claim scope
-----------
Proves: the saved bytes contain five graphs with the stated node counts, five bindings on
the level entity, the unchanged 34 tiles, and the retired graphs' start edge still absent.
Does NOT prove: that the level reopens identically, that the demo graph runs, or that any
playtest succeeds.

Usage
-----
  python tools/editor-bridge/verify-five-graph-snapshot.py <snapshot.gil> [--output report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('four_graph', _HERE / 'verify-four-graph-snapshot.py')
four = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(four)

DEMO_GRAPH_ID = 1073741829
DEMO_GRAPH_NAME = 'MW_Game_Loop_20260917'

EXPECTED_GRAPHS = dict(four.EXPECTED_GRAPHS)
EXPECTED_GRAPHS[DEMO_GRAPH_ID] = (29, DEMO_GRAPH_NAME)

# The demo graph carries the same start edge the other active graphs do, so it joins them
# as a positive control rather than being exempt from the check.
ACTIVE_SPAWN_GRAPHS = tuple(four.ACTIVE_SPAWN_GRAPHS) + (DEMO_GRAPH_ID,)
RETIRED_GRAPHS = tuple(four.RETIRED_GRAPHS)


def verify(path: Path) -> dict:
    from miliastra_agent.parsers.gil import parse_gi_file

    parsed = parse_gi_file(path)
    header, _payload, raw_graphs = four._load_graphs(path)
    checks = four.Check()

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checks.add('header.file_type', 'container is a GIL level save', four.GIL_FILE_TYPE, header.file_type)

    found = {int(g.identity.runtime_id): g for g in raw_graphs}
    # ``Check.add(check_id, description, expected, actual, ok=None)`` -- the verdict is
    # ``expected == actual`` when ``ok`` is omitted.  This call used to pass FIVE
    # arguments, so ``ok`` received ``sorted(found)`` (a list, always truthy once any
    # graph exists) and the comparison landed in ``expected``: the row printed
    # ``expected=False`` beside ``pass=True`` and the check could not fail.  MEASURED
    # 2026-10-03: a byte-clone of the demo graph added as a SIXTH graph scored 44/44
    # before this fix and 43/44 after, the single red row being ``graphs.ids``.  The
    # per-graph node/name checks below do catch a MISSING expected graph; this one is
    # the only assertion that catches an EXTRA one.
    checks.add('graphs.ids', 'exactly the five expected graph ids',
               sorted(EXPECTED_GRAPHS), sorted(found))
    for graph_id, (node_count, display_name) in EXPECTED_GRAPHS.items():
        graph = found.get(graph_id)
        checks.add(f'graph.{graph_id}.nodes', f'{display_name} node count',
                   node_count, None if graph is None else len(graph.nodes))
        checks.add(f'graph.{graph_id}.name', f'{graph_id} display name',
                   display_name, None if graph is None else graph.display_name)

    for graph_id in RETIRED_GRAPHS:
        graph = found.get(graph_id)
        targets = [] if graph is None else four.start_edge_targets(graph)
        checks.add(f'retired.{graph_id}.start_edge_absent',
                   f'{graph_id} start OUT_FLOW0 must not reach node {four.NEXT_NODE_INDEX}',
                   f'{four.NEXT_NODE_INDEX} absent', targets, ok=four.NEXT_NODE_INDEX not in targets)
        total = None if graph is None else four.count_connections(graph)
        checks.add(f'retired.{graph_id}.not_vacuous',
                   f'{graph_id} still carries its own connections',
                   '> 0 connections', total, ok=total is not None and total > 0)

    for graph_id in ACTIVE_SPAWN_GRAPHS:
        graph = found.get(graph_id)
        targets = [] if graph is None else four.start_edge_targets(graph)
        checks.add(f'active.{graph_id}.start_edge_present',
                   f'{graph_id} start OUT_FLOW0 must reach node {four.NEXT_NODE_INDEX} (detector control)',
                   f'{four.NEXT_NODE_INDEX} present', targets, ok=four.NEXT_NODE_INDEX in targets)

    bindings = parsed.entity_graph_bindings
    checks.add('bindings.count', 'five entity-graph bindings', 5, len(bindings))
    checks.add('bindings.entity', 'all bindings belong to the level entity',
               [four.LEVEL_ENTITY_ID], sorted({b.entity_id for b in bindings}))
    checks.add('bindings.graphs', 'bindings cover exactly the five graphs',
               sorted(EXPECTED_GRAPHS), sorted({b.graph_id for b in bindings}))
    checks.add('bindings.demoGraphBound', 'the demo graph is bound to the level entity',
               True, DEMO_GRAPH_ID in {b.graph_id for b in bindings})

    static = [e for e in parsed.entities if four.STATIC_NAME.match(e.name)]
    checks.add('static.count', 'thirty-four MW_Static_* tiles still present', 34, len(static))
    from collections import Counter
    checks.add('static.templates', 'template mix unchanged by the demo graph',
               four.EXPECTED_TEMPLATE_MIX,
               dict(sorted(Counter(e.template_id for e in static).items())))

    by_platform: dict[int, list] = {}
    for entity in static:
        by_platform.setdefault(int(four.STATIC_NAME.match(entity.name).group(1)), []).append(entity)
    checks.add('static.platforms', 'platform indexes present',
               sorted(four.EXPECTED_PLATFORMS), sorted(by_platform))
    for index, (expected_count, cx, cy, cz) in four.EXPECTED_PLATFORMS.items():
        tiles = by_platform.get(index, [])
        checks.add(f'platform.{index}.count', f'P{index} tile count', expected_count, len(tiles))
        if not tiles:
            continue
        xs = [t.position.x for t in tiles]
        zs = [t.position.z for t in tiles]
        checks.add(f'platform.{index}.centre', f'P{index} centre x/z', (cx, cz),
                   (round((min(xs) + max(xs)) / 2, four.ROUND), round((min(zs) + max(zs)) / 2, four.ROUND)))
        checks.add(f'platform.{index}.height', f'P{index} height y', [round(cy, four.ROUND)],
                   sorted({round(t.position.y, four.ROUND) for t in tiles}))

    return {
        'ok': checks.ok,
        'snapshot': str(path),
        'sha256': digest,
        'bytes': path.stat().st_size,
        'levelName': parsed.level_name,
        'graphIds': sorted(EXPECTED_GRAPHS),
        'bindingCount': len(bindings),
        'demoGraphId': DEMO_GRAPH_ID,
        'demoGraphBound': DEMO_GRAPH_ID in {b.graph_id for b in bindings},
        'claimScope': {
            'proves': ['the saved bytes contain five graphs with the stated node counts',
                       'five bindings on the level entity, including the demo graph',
                       'the 34 tiles and the retired start edges are unchanged'],
            'doesNotProve': ['the level reopens identically', 'the demo graph executes',
                             'any playtest succeeds'],
        },
        'checks': checks.rows,
        'failed': [row['id'] for row in checks.rows if not row['pass']],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Independently verify a five-graph .gil snapshot.')
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding='utf-8')
    if not args.snapshot.is_file():
        print(json.dumps({'ok': False, 'reason': f'no such snapshot: {args.snapshot}'}, ensure_ascii=False))
        return four.EXIT_MISSING

    try:
        report = verify(args.snapshot)
    except Exception as exc:
        refusal = {'ok': False, 'refused': 'snapshot is not a parseable GIL level save; no verdict is claimed',
                   'snapshot': str(args.snapshot), 'parseError': f'{exc.__class__.__name__}: {exc}',
                   'sha256': four._safe_digest(args.snapshot), 'bytes': args.snapshot.stat().st_size}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(refusal, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(refusal, ensure_ascii=False, indent=2))
        return four.EXIT_CORRUPT

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in report['checks']:
        print(f"[{'PASS' if row['pass'] else 'FAIL'}] {row['id']}: "
              f"expected={row['expected']!r} actual={row['actual']!r}")
    print()
    print(f"checks={len(report['checks'])} failed={len(report['failed'])} ok={report['ok']}")
    if report['failed']:
        print('failed:', ', '.join(report['failed']))
    return four.EXIT_OK if report['ok'] else four.EXIT_CHECKS_FAILED


if __name__ == '__main__':
    raise SystemExit(main())
