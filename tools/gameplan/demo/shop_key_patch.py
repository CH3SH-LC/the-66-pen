"""Offline Z-shop candidate and exact patch for the user-tested R7 shop graph.

No execution/queue/bridge entry point. The new standalone player graph is a
comparison example; use the combined farming_manual player graph instead when
both are packaged. Never attach two competing controls/graphs for the same Z.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from ..builder import GraphBuilder
from ..nodes import Graph, OPEN_SHOP, PRINT
from ..modules import key_interaction as key
from ..modules.distance_interaction import ENTITY

ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = ROOT / '.runtime/scratch/offline-farming-20261014/key-input'
BASE_GIA = ROOT / '.runtime/editor-bridge/exports/miliastra-bridge-1faa300c-0b13-4428-a0f8-881cb27de9c2/bridge-export-6014011a259c422dbb635480f61d6a30.gia'
BASE_GIL = ROOT / '.runtime/game-executor/scene-cli/20261014-013620-save-aebbabd5/after-1073741842.gil'
GIA_SHA = '44340fcc3209d96504bf0b556db7389e11637c38889c57d81411f6d200a84600'
GIL_SHA = 'b8a49d0e3fb0befd84ee5c3b6ea412e247fcd740e4d563f49e197ad1f942608b'
GRAPH_ID, SHOP_ENTITY_ID, SHOP_INDEX = 1073741834, 1077936129, 1
DISCONNECT = ((44, 0, 46), (41, 1, 46))


def _decoder():
    spec = importlib.util.spec_from_file_location('key_shop_saved_decoder', ROOT / 'tools/editor-bridge/audit-native-enums.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path):
    raw, graphs = _decoder().load_graphs(Path(path))
    found = [g for g in graphs if g.identity.runtime_id == GRAPH_ID]
    if len(found) != 1:
        raise ValueError('R7_SHOP_GRAPH_NOT_UNIQUE')
    return raw, found[0]


def _pin(node, kind, index):
    pins = [p for p in node.pins if (p.shell_sig.kind, p.shell_sig.index) == (kind, index)]
    if len(pins) != 1:
        raise ValueError('PIN_NOT_UNIQUE')
    return pins[0]


def _baseline(baseline_gia=BASE_GIA, baseline_gil=BASE_GIL):
    raw, graph = _load(baseline_gia)
    saved_raw, saved_graph = _load(baseline_gil)
    if hashlib.sha256(raw).hexdigest() != GIA_SHA or hashlib.sha256(saved_raw).hexdigest() != GIL_SHA:
        raise ValueError('REAL_R7_BASELINE_HASH_MISMATCH')
    if graph.SerializeToString() != saved_graph.SerializeToString():
        raise ValueError('R7_EXPORT_SAVE_GRAPH_MISMATCH')
    return graph


def expected_patched_graph(*, baseline_gia=BASE_GIA, baseline_gil=BASE_GIL):
    graph = _baseline(baseline_gia, baseline_gil)
    nodes = {n.index: n for n in graph.nodes}
    for source, output, target in DISCONNECT:
        pin = _pin(nodes[source], 2, output)
        if (len(pin.connections) != 1 or pin.connections[0].target_node_index != target or
                pin.connections[0].target_pin_shell.kind != 1 or
                pin.connections[0].target_pin_shell.index != 0):
            raise ValueError('R7_AUTOMATIC_OPEN_EDGE_MISMATCH')
        pin.ClearField('connections')
    return graph


def prepare_patch(*, baseline_gia=BASE_GIA, baseline_gil=BASE_GIL):
    expected = expected_patched_graph(baseline_gia=baseline_gia, baseline_gil=baseline_gil)
    return {'kind': 'offline-shop-z-patch-v1', 'graphId': GRAPH_ID,
        'candidateOnly': True, 'dispatchable': False, 'runtimeVerified': False,
        'baselineGiaSha256': GIA_SHA, 'baselineGilSha256': GIL_SHA,
        'expectedGraphPayloadSha256': hashlib.sha256(expected.SerializeToString()).hexdigest(),
        'beforeShape': [62, 82, 63], 'afterShape': [62, 80, 63],
        'preserved': ['all 62 nodes', 'all 63 planned constants', 'prices/count2',
                      'catalog initialization', 'starter guard/currency', 'all other connections'],
        'operations': [{'action': 'disconnect', 'graphId': GRAPH_ID,
            'fromNodeId': source, 'fromPortKind': 2, 'fromPortIndex': output,
            'toNodeId': target, 'toPortKind': 1, 'toPortIndex': 0}
            for source, output, target in DISCONNECT],
        'ordinaryUnwireAllowedOnBoundGraph': False,
        'ordinaryUnwireRefusal': 'AUTHOR_BOUND_GRAPH_EDIT_REFUSED',
        'boundGraphRuleSource': 'tools/editor-bridge/Adapter/AuthoringGraph.cs:343',
        'deploymentRequires': 'separate reviewed fixed sync handler or proven binding replacement',
        'requiredBeforeDeployment': ['single UI interaction-event control mapped to Z',
            'actual UI group index', 'player-side graph binding',
            'fresh session and independently reviewed graph patch',
            'native export/save comparison and Z playtest'],
        'note': 'Player-side graph opens the existing shop. Its player event cannot run on the shop scene host.'}


def verify_patch_export(path):
    raw, graph = _load(path)
    return {'inputSha256': hashlib.sha256(raw).hexdigest(), **verify_patch_graph(graph)}


def verify_patch_graph(graph):
    expected = expected_patched_graph()
    exact = graph.SerializeToString() == expected.SerializeToString()
    return {'ok': exact, 'serializedContentVerified': exact, 'runtimeVerified': False,
        'errors': [] if exact else ['NOT_R7_WITH_ONLY_TWO_AUTOMATIC_OPEN_EDGES_REMOVED']}


def add_open_shop(g, src, *, player, character, shop_owner, center=(0, 0, 0),
                  radius=1.5, index=SHOP_INDEX, from_role='true', alias='key_shop'):
    near = key.near(g, src, character=character, center=center, radius=radius,
                    alias=alias + '_near', from_role=from_role)
    opened = g.place(OPEN_SHOP, alias + '_open')
    near.flow_to(opened, 'true')
    opened.data_from(*player, 'player')
    opened.data_from(*shop_owner, 'shop_owner')
    opened.const('shop_index', key.abilities.integer(index, 'shop_index', minimum=1), 'int')
    note = g.place(PRINT, alias + '_note')
    opened.flow_to(note)
    note.const('text', 'SHOP_Z_OPEN_REQUESTED', 'string')
    return opened


def build_player_plan(group_index, group_combo_index=None):
    g = Graph('MW_API_SHOP_Z_PLAYER')
    control = key.on_control(g, group_index=group_index, group_combo_index=group_combo_index)
    character = key.character_for_player(g, control.gate, player=control.player)
    owner = g.place(ENTITY, 'shop_owner')
    owner.const('guid', SHOP_ENTITY_ID, 'uint')  # Actual scene entity GUID, never character GUID.
    add_open_shop(g, character.gate, player=control.player, character=character.character,
                  shop_owner=(owner, 'entity'))
    g.validate()
    return g.plan


def compile_player_plan(group_index, group_combo_index=None):
    plan = build_player_plan(group_index, group_combo_index)
    def never_dispatch(_):
        raise AssertionError('OFFLINE_ONLY')
    return GraphBuilder(plan, never_dispatch, run_id='offline-only').batch_plan_json()


def write_package(out_dir, *, baseline_gia=BASE_GIA, baseline_gil=BASE_GIL, group_index):
    out = Path(out_dir).resolve()
    if not out.is_relative_to(OUT_ROOT):
        raise ValueError('OUTPUT_MUST_BE_INSIDE_KEY_INPUT_SCRATCH')
    patch = prepare_patch(baseline_gia=baseline_gia, baseline_gil=baseline_gil)
    compiled = compile_player_plan(group_index)
    if len(json.dumps(compiled, separators=(',', ':')).encode()) >= 16000:
        raise ValueError('PLAYER_GRAPH_REQUEST_TOO_LARGE')
    out.mkdir(parents=True, exist_ok=False)
    outputs = {'shop-auto-open-patch.json': patch, 'standalone-player-graph.json': compiled,
        'deployment.json': {'candidateOnly': True, 'dispatchable': False,
            'runtimeVerified': False, 'keyboardKey': 'Z', 'keyboardMappingValue': None,
            'groupIndex': group_index, 'graphHostRequired': 'triggering player',
            'uiGroupExistsVerified': False, 'standaloneGraphIsComparisonOnly': True,
            'doNotBindWithCombinedFarmingPlayerGraph': True}}
    for name, data in outputs.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return {name: str(out / name) for name in outputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group-index', required=True, type=int)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(write_package(args.out_dir, group_index=args.group_index), indent=2))


if __name__ == '__main__':
    main()
