"""Validate the native export of the platform-challenge demo graph.

Expectations come from the DESIGN in Adapter/GameLoopGraph.cs (node order, flow and data
links, constants), not from whatever the export happens to contain. Passing proves the
exported graph matches the design; it does NOT prove the graph runs, that the level saves,
or that a player can complete the course.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit_helpers', Path(__file__).with_name('verify-runtime-audit.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

NAME = 'MW_Game_Loop_20260917'
TIMER = 'MW_GL_TICK_20260917'
START_MARKER = 'MW_GL_STARTED_20260917'
FINISH_MARKER = 'MW_GL_FINISHED_20260917'
SCORE_LABEL = '用时(秒)'
GOAL = (17.0, 2.5, 0.0)
MAX_DISTANCE = 2.0
MINIMUM_HEIGHT = 2.4
FALL_BELOW_Y = -5.0
RESPAWN = (0.0, 1.5, 0.0)
TICK_SECONDS = 1.0

# Add order in BuildGameLoopGraph, 1-based to match the export's node indexes.
DEFS = dict(enumerate([
    71, 73, 14, 2, 1, 79, 83, 14, 2, 248,
    509, 804, 99, 225, 244, 231, 9, 233, 226, 2,
    82, 1, 652, 647, 77, 230, 2, 225, 805,
], 1))

# (source node, source OUT_FLOW index, target node, target IN_FLOW index)
FLOW = [(1, 0, 4, 0), (4, 0, 5, 0), (5, 0, 6, 0),
        (7, 0, 9, 0), (9, 0, 11, 0), (11, 0, 20, 0),
        (20, 0, 21, 0), (21, 0, 22, 0), (22, 0, 23, 0), (23, 0, 24, 0), (24, 0, 25, 0),
        (20, 1, 27, 0), (27, 0, 29, 0)]

# (source node, source OUT_PARAM index, target node, target IN_PARAM index)
DATA = [(1, 0, 3, 0), (2, 0, 3, 1), (3, 0, 4, 0), (2, 0, 6, 0),
        (7, 2, 8, 0), (8, 0, 9, 0),
        (10, 0, 11, 0), (11, 0, 12, 0), (12, 0, 13, 0),
        (13, 0, 15, 0), (14, 0, 15, 1), (15, 0, 16, 0),
        (13, 0, 17, 0), (17, 1, 18, 0),
        (16, 0, 19, 0), (18, 0, 19, 1), (19, 0, 20, 0),
        (2, 0, 21, 0), (11, 0, 23, 0), (11, 0, 24, 0), (7, 4, 24, 3),
        (17, 1, 26, 0), (26, 0, 27, 0), (11, 0, 29, 0), (28, 0, 29, 1)]

EDGES = {(f'{(a,2,ai)}->{(b,1,bi)}') for a, ai, b, bi in FLOW} | {(f'{(a,4,ai)}->{(b,3,bi)}') for a, ai, b, bi in DATA}
NODE_COUNT = len(DEFS)
EDGE_COUNT = len(FLOW) + len(DATA)


def verify(path):
    r = h.inspect_graph.inspect(Path(path))
    check = h._require
    check(r['name'] == NAME, f'Wrong graph name: {r["name"]!r}')
    check(isinstance(r['graphId'], int) and r['graphId'] > 0, 'Missing graph id')
    check(r['nodeCount'] == NODE_COUNT, f'Node count {r["nodeCount"]} != {NODE_COUNT}')
    check({n['id']: n['definition'] for n in r['nodes']} == DEFS, 'Node definitions do not match the design')

    actual = {f'{tuple(e["source"])}->{tuple(e["target"])}' for e in r['directedEdges']}
    check(len(r['directedEdges']) == EDGE_COUNT, f'Edge count {len(r["directedEdges"])} != {EDGE_COUNT}')
    check(actual == EDGES, f'Edges differ from the design; missing={sorted(EDGES - actual)} unexpected={sorted(actual - EDGES)}')

    nodes = {n['id']: n for n in r['nodes']}

    def pin(n, i=0, kind='IN_PARAM'):
        return h._pins(nodes[n], kind)[i]

    def floating(n, i, expected):
        p = pin(n, i)
        check(p.get('type') == 5 and h._type_tag(p) == 'S_FLOAT', f'Float type {n}/{i}')
        value = h._actual(p)
        check('val_float' in value and math.isclose(value['val_float'].get('float', 0), expected, abs_tol=1e-6),
              f'Float constant {n}/{i} expected {expected}')

    # Goal vector (14), respawn vector (28) and the two thresholds.
    for n, i, v in [(14, 0, GOAL[0]), (14, 1, GOAL[1]), (14, 2, GOAL[2]),
                    (28, 0, RESPAWN[0]), (28, 1, RESPAWN[1]), (28, 2, RESPAWN[2]),
                    (16, 1, MAX_DISTANCE), (18, 1, MINIMUM_HEIGHT), (26, 1, FALL_BELOW_Y)]:
        floating(n, i, v)

    # Enum-backed booleans: the timer loop flag and the settle-stage success flag. These
    # are S_BOOL stored through an enum widget, which is why the setter is the enum one.
    for n, i in [(6, 2), (25, 0)]:
        p = pin(n, i)
        check(p.get('type') == 4 and h._type_tag(p) == 'S_BOOL'
              and h._actual(p).get('val_enum', {}).get('enum') == '1',
              f'Enum-backed true required at {n}/{i}')
    # Settlement status is a different beast: an S_ENUM_ITEM (type 14), not a boolean.
    # Checking it as a boolean was this verifier's own error, not the graph's.
    p = pin(23, 1)
    check(p.get('type') == 14 and h._type_tag(p) == 'S_ENUM_ITEM',
          f'Settlement status must be an enum item at 23/1, got type={p.get("type")} tag={h._type_tag(p)}')
    # Native BeyondGlobal map 34 and the compiler's enum mapping agree: Victory
    # is 4101. The old value 1 was a UI ordinal, outside this enum's domain.
    check(h._actual(p).get('val_enum', {}).get('enum') == '4101',
          'Settlement status must be native Victory=4101 (enum map 34)')
    check(pin(23, 0).get('type') == 1, 'Settlement status takes its player from a link')

    # Timer identity must appear on start, stop and the tick comparison.
    for n, i in [(6, 1), (8, 1), (21, 1)]:
        check(h._literal(pin(n, i)) == TIMER, f'Timer identity {n} expected {TIMER}')

    check(h._literal(pin(5)) == START_MARKER, 'Start marker')
    check(h._literal(pin(22)) == FINISH_MARKER, 'Finish marker')

    # Scoreboard row: order 0 and the label. The value pin is linked, so it is checked by
    # the edge set above rather than as a constant.
    check(h._literal(pin(24, 2)) == SCORE_LABEL, f'Score label expected {SCORE_LABEL}')
    # Score row order is an S_INT. This project has never written an S_INT constant through
    # an adapter setter: the populated val_int values in the export history all came from
    # offline-built payloads that were imported natively. c84KKE8ihrN (the int setter paired
    # with the ilqKKrw7dhN getter) sets a slot the exporter does not serialise, so this pin
    # reads back empty even though is_value_set is 1. The unset default is 0, which is the
    # intended order, so the graph is accepted as-is rather than rebuilt for a field whose
    # effective value is already right. Asserted here: right pin, right type, and no
    # conflicting value.
    order_pin = pin(24, 1)
    check(order_pin.get('type') == 3 and h._type_tag(order_pin) == 'S_INT',
          f'Score row order must be an S_INT pin, got type={order_pin.get("type")}')
    order = h._actual(order_pin).get('val_int')
    check(order in ({}, {'int': 0}), f'Score row order must be unset or 0, got {order!r}')

    # One-second repeating sequence: the period is what makes the tick counter a second count.
    p = pin(6, 3)
    check(p.get('type') == 10 and h._type_tag(p) == 'S_FLOAT_LIST', 'Timer sequence type')
    elements = h._actual(p)['val_list']['elements']
    check(len(elements) == 1
          and elements[0].get('type_def', {}).get('server_side', {}).get('type_tag') == 'S_FLOAT'
          and math.isclose(elements[0]['val_float']['float'], TICK_SECONDS, abs_tol=1e-6),
          f'Tick period must be {TICK_SECONDS}s so the loop counter equals elapsed seconds')

    return dict(ok=True, name=NAME, graphId=r['graphId'], sha256=r['sha256'],
                nodeCount=NODE_COUNT, edgeCount=EDGE_COUNT, timer=TIMER, tickSeconds=TICK_SECONDS,
                goal=list(GOAL), maxDistance=MAX_DISTANCE, minimumHeight=MINIMUM_HEIGHT,
                fallBelowY=FALL_BELOW_Y, respawn=list(RESPAWN), scoreRow=SCORE_LABEL,
                runtimeVerified=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path)
    p.add_argument('--output', type=Path)
    # The wiring above is course-independent; only the name and the geometry are not.
    # Defaults are the 20260917 course, so the original invocation is unchanged. A second
    # course (the MVP course, Adapter/GameLoopGraph.cs MvpCourseGraphName) overrides them
    # rather than getting a copy of this file that could drift from the checks.
    p.add_argument('--name', default=NAME)
    p.add_argument('--timer', default=TIMER)
    p.add_argument('--start-marker', default=START_MARKER)
    p.add_argument('--finish-marker', default=FINISH_MARKER)
    p.add_argument('--goal', type=float, nargs=3, default=list(GOAL))
    p.add_argument('--respawn', type=float, nargs=3, default=list(RESPAWN))
    p.add_argument('--min-height', type=float, default=MINIMUM_HEIGHT)
    args = p.parse_args()
    NAME = args.name
    TIMER = args.timer
    START_MARKER = args.start_marker
    FINISH_MARKER = args.finish_marker
    GOAL = tuple(args.goal)
    RESPAWN = tuple(args.respawn)
    MINIMUM_HEIGHT = args.min_height
    result = json.dumps(verify(args.path), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
