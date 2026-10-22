#!/usr/bin/env python3
"""Independent checker for a four-graph level snapshot (.gil).

Every expected value below is transcribed from the project handoff
(`docs/ds-handoff/01-STATE-AND-EVIDENCE.md` §3) and the R51 finish-graph
independent verifier — NOT from this script's own parser output. The point is
that the checker and the snapshot come from different places.

Controls
--------
* Retired graphs are checked two ways: the start edge must be absent AND the
  graph must still hold other connections. Without the second check an empty
  graph would trivially "pass" as retired.
* The active graphs must still HAVE the same start edge. This is the positive
  control: it proves the detector detects the edge at all, so an absent edge in
  the retired graphs is a real absence rather than a broken search.
* Pass/fail is derived from `expected == actual` unless a check explicitly
  overrides it, so a row can never claim PASS while its own evidence disagrees.

Claim scope
-----------
Proves: the snapshot bytes contain the stated graphs, bindings, entities and
start-edge states.
Does NOT prove: that the game flushed this content, that the editor currently
shows it, that the level reopens identically, or that any graph runs.

Usage
-----
  python tools/editor-bridge/verify-four-graph-snapshot.py <snapshot.gil> [--output report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_SRC = REPO_ROOT / 'third_party/auto-miliastra/src'
if str(PARSER_SRC) not in sys.path:
    sys.path.insert(0, str(PARSER_SRC))

# --- expectations transcribed from the handoff, not derived from the parser ---
EXPECTED_GRAPHS = {
    1073741825: (7, 'MW_Platform_Calibration_20260916'),
    1073741826: (39, 'MW_Route_Tiled_20260916'),
    1073741827: (16, 'MW_Character_Position_20260916'),
    1073741828: (23, 'MW_Course_Finish_20260916'),
}
RETIRED_GRAPHS = (1073741825, 1073741826)
ACTIVE_SPAWN_GRAPHS = (1073741827, 1073741828)
FINISH_GRAPH_ID = 1073741828
FINISH_GRAPH_CONNECTIONS = 27
LEVEL_ENTITY_ID = 1094713345
GIL_FILE_TYPE = 2
EXPECTED_TEMPLATE_MIX = {20001224: 8, 20001875: 9, 20001876: 4, 20001877: 4, 20001878: 9}

# platform -> (tile count, nominal centre x, y, z); top face == y + 0.5
EXPECTED_PLATFORMS = {
    0: (9, 0.0, 0.0, 0.0),
    1: (4, 3.7, 0.4, 0.0),
    2: (4, 6.9, 0.8, 0.0),
    3: (4, 10.1, 1.2, 0.0),
    4: (4, 13.3, 1.6, 0.0),
    5: (9, 17.0, 2.0, 0.0),
}
STATIC_NAME = re.compile(r'^MW_Static_P(\d+)_Tile(\d+)$')

OUT_FLOW_KIND = 2
START_NODE_INDEX = 1
NEXT_NODE_INDEX = 4
START_PIN_INDEX = 0
ROUND = 5

EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_MISSING = 4
EXIT_CORRUPT = 5


def _safe_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class Check:
    """Collects rows. `ok` defaults to `expected == actual` so evidence and verdict cannot drift."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, check_id: str, description: str, expected, actual, ok: bool | None = None) -> bool:
        verdict = (expected == actual) if ok is None else bool(ok)
        self.rows.append({'id': check_id, 'description': description, 'pass': verdict,
                          'expected': expected, 'actual': actual})
        return verdict

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(row['pass'] for row in self.rows)


def _load_graphs(path: Path):
    from miliastra_agent.core.gi_file import read_header, read_payload
    from miliastra_agent.core.proto_gen import gia_graph_pb2 as graph_pb
    from miliastra_agent.core.wire import get_bytes_fields

    payload = read_payload(path)
    header = read_header(path.read_bytes())
    field10 = get_bytes_fields(payload, 10)
    graphs = []
    if field10:
        for wrapper in get_bytes_fields(field10[0], 1):
            inner = get_bytes_fields(wrapper, 1)
            if not inner:
                continue
            graph = graph_pb.NodeGraph()
            graph.ParseFromString(inner[0])
            graphs.append(graph)
    return header, payload, graphs


def start_edge_targets(graph) -> list[int]:
    """Target node indexes reachable from the start node's OUT_FLOW pin 0."""
    targets: list[int] = []
    for node in graph.nodes:
        if node.index != START_NODE_INDEX:
            continue
        for pin in node.pins:
            if pin.kernel_sig.kind != OUT_FLOW_KIND or pin.kernel_sig.index != START_PIN_INDEX:
                continue
            targets.extend(conn.target_node_index for conn in pin.connections)
    return sorted(targets)


def count_connections(graph) -> int:
    return sum(len(pin.connections) for node in graph.nodes for pin in node.pins)


def verify(path: Path) -> dict:
    from miliastra_agent.parsers.gil import parse_gi_file

    parsed = parse_gi_file(path)
    header, _payload, raw_graphs = _load_graphs(path)
    checks = Check()

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checks.add('header.file_type', 'container is a GIL level save', GIL_FILE_TYPE, header.file_type)

    found = {int(g.identity.runtime_id): g for g in raw_graphs}
    checks.add('graphs.ids', 'exactly the four expected graph ids',
               sorted(EXPECTED_GRAPHS), sorted(found))
    for graph_id, (node_count, display_name) in EXPECTED_GRAPHS.items():
        graph = found.get(graph_id)
        checks.add(f'graph.{graph_id}.nodes', f'{display_name} node count',
                   node_count, None if graph is None else len(graph.nodes))
        checks.add(f'graph.{graph_id}.name', f'{graph_id} display name',
                   display_name, None if graph is None else graph.display_name)

    finish = found.get(FINISH_GRAPH_ID)
    checks.add('finish.connections', 'finish graph connection count matches R51 design',
               FINISH_GRAPH_CONNECTIONS, None if finish is None else count_connections(finish))

    # --- retirement of the old runtime-spawn graphs -------------------------
    for graph_id in RETIRED_GRAPHS:
        graph = found.get(graph_id)
        targets = [] if graph is None else start_edge_targets(graph)
        checks.add(f'retired.{graph_id}.start_edge_absent',
                   f'{graph_id} start OUT_FLOW0 must not reach node {NEXT_NODE_INDEX}',
                   f'{NEXT_NODE_INDEX} absent', targets, ok=NEXT_NODE_INDEX not in targets)
        total = None if graph is None else count_connections(graph)
        checks.add(f'retired.{graph_id}.not_vacuous',
                   f'{graph_id} still carries its own connections (absence is not emptiness)',
                   '> 0 connections', total, ok=total is not None and total > 0)

    # --- positive control: active graphs must still HAVE the edge -----------
    for graph_id in ACTIVE_SPAWN_GRAPHS:
        graph = found.get(graph_id)
        targets = [] if graph is None else start_edge_targets(graph)
        checks.add(f'active.{graph_id}.start_edge_present',
                   f'{graph_id} start OUT_FLOW0 must still reach node {NEXT_NODE_INDEX} (detector control)',
                   f'{NEXT_NODE_INDEX} present', targets, ok=NEXT_NODE_INDEX in targets)

    # --- bindings -----------------------------------------------------------
    bindings = parsed.entity_graph_bindings
    checks.add('bindings.count', 'four entity-graph bindings', 4, len(bindings))
    checks.add('bindings.entity', 'all bindings belong to the level entity',
               [LEVEL_ENTITY_ID], sorted({b.entity_id for b in bindings}))
    checks.add('bindings.graphs', 'bindings cover exactly the four graphs',
               sorted(EXPECTED_GRAPHS), sorted({b.graph_id for b in bindings}))

    # --- static platform entities ------------------------------------------
    static = [e for e in parsed.entities if STATIC_NAME.match(e.name)]
    checks.add('static.count', 'thirty-four MW_Static_* tiles', 34, len(static))

    by_platform: dict[int, list] = {}
    for entity in static:
        by_platform.setdefault(int(STATIC_NAME.match(entity.name).group(1)), []).append(entity)

    checks.add('static.platforms', 'platform indexes present',
               sorted(EXPECTED_PLATFORMS), sorted(by_platform))
    for index, (expected_count, cx, cy, cz) in EXPECTED_PLATFORMS.items():
        tiles = by_platform.get(index, [])
        checks.add(f'platform.{index}.count', f'P{index} tile count', expected_count, len(tiles))
        if not tiles:
            continue
        xs = [t.position.x for t in tiles]
        zs = [t.position.z for t in tiles]
        centre = (round((min(xs) + max(xs)) / 2, ROUND), round((min(zs) + max(zs)) / 2, ROUND))
        checks.add(f'platform.{index}.centre', f'P{index} centre x/z', (cx, cz), centre)
        heights = sorted({round(t.position.y, ROUND) for t in tiles})
        checks.add(f'platform.{index}.height', f'P{index} height y', [round(cy, ROUND)], heights)
        rotations = sorted({(round(t.rotation.x, ROUND), round(t.rotation.y, ROUND), round(t.rotation.z, ROUND))
                            for t in tiles})
        checks.add(f'platform.{index}.rotation', f'P{index} zero rotation', [(0.0, 0.0, 0.0)], rotations)
        scales = sorted({(round(t.scale.x, ROUND), round(t.scale.y, ROUND), round(t.scale.z, ROUND))
                         for t in tiles})
        checks.add(f'platform.{index}.scale', f'P{index} unit scale', [(1.0, 1.0, 1.0)], scales)

    checks.add('static.templates', 'template mix totals 34 across five prefabs',
               EXPECTED_TEMPLATE_MIX, dict(sorted(Counter(e.template_id for e in static).items())))

    return {
        'ok': checks.ok,
        'snapshot': str(path),
        'sha256': digest,
        'bytes': path.stat().st_size,
        'levelName': parsed.level_name,
        'claimScope': {
            'proves': ['snapshot bytes contain the stated graphs, bindings and tile entities',
                       "the retired graphs' start edge is absent while the active graphs' is present"],
            'doesNotProve': ['the game flushed this content', 'the editor currently shows it',
                             'the level reopens identically', 'any graph executes at runtime'],
        },
        'checks': checks.rows,
        'failed': [row['id'] for row in checks.rows if not row['pass']],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Independently verify a four-graph .gil snapshot.')
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding='utf-8')
    if not args.snapshot.is_file():
        print(json.dumps({'ok': False, 'reason': f'no such snapshot: {args.snapshot}'}, ensure_ascii=False))
        return EXIT_MISSING

    try:
        report = verify(args.snapshot)
    except Exception as exc:  # truncated, tampered or non-GIL input: refuse, never crash-report
        refusal = {
            'ok': False,
            'refused': 'snapshot is not a parseable GIL level save; no verdict is claimed',
            'snapshot': str(args.snapshot),
            'parseError': f'{exc.__class__.__name__}: {exc}',
            'sha256': _safe_digest(args.snapshot),
            'bytes': args.snapshot.stat().st_size,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(refusal, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(refusal, ensure_ascii=False, indent=2))
        return EXIT_CORRUPT
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
    return EXIT_OK if report['ok'] else EXIT_CHECKS_FAILED


if __name__ == '__main__':
    raise SystemExit(main())
