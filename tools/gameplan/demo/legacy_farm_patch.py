"""Prepare a precise old-auto-farm detach; no editor calls or save-file writes."""
import hashlib
import importlib.util
from pathlib import Path

from .offline_farming_baseline import BASELINE_GIL, BASELINE_SHA, ROOT

GRAPH_ID = 1073741835
GRAPH_NAME = 'MW_API_MIN_FARM_1077936130'
# Disable creation/polling, seed consumption entry, and automatic harvest entry.
EDGES = ((5, 7), (41, 43), (52, 54))


def _loader():
    spec = importlib.util.spec_from_file_location('offline_legacy_farm_loader',
        ROOT/'tools/editor-bridge/audit-native-enums.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def graph_at(path):
    raw, graphs = _loader().load_graphs(Path(path))
    matches = [g for g in graphs if g.identity.runtime_id == GRAPH_ID]
    if len(matches) != 1 or matches[0].display_name != GRAPH_NAME:
        raise ValueError('OLD_FARM_IDENTITY_MISMATCH')
    return raw, matches[0]


def baseline():
    raw, graph = graph_at(BASELINE_GIL)
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA or len(graph.nodes) != 56:
        raise ValueError('OLD_FARM_BASELINE_CHANGED')
    return graph


def remove_exact_entries(graph):
    """Modify only an in-memory copy, and refuse any already-applied edge."""
    expected = type(graph)()
    expected.CopyFrom(graph)
    for source, target in EDGES:
        nodes = [n for n in expected.nodes if n.index == source]
        if len(nodes) != 1:
            raise ValueError('OLD_FARM_SOURCE_NOT_UNIQUE')
        pins = [p for p in nodes[0].pins if (p.shell_sig.kind, p.shell_sig.index) == (2, 0)]
        if len(pins) != 1:
            raise ValueError('OLD_FARM_SOURCE_PIN_NOT_UNIQUE')
        pin = pins[0]
        matches = [i for i, c in enumerate(pin.connections)
                   if (c.target_node_index, c.target_pin_shell.kind, c.target_pin_shell.index,
                       c.target_pin_kernel.kind, c.target_pin_kernel.index) == (target, 1, 0, 1, 0)]
        if len(matches) != 1:
            raise ValueError('OLD_FARM_EDGE_NOT_PRESENT_ONCE')
        del pin.connections[matches[0]]
    return expected


def prepare_patch():
    old = baseline()
    expected = remove_exact_entries(old)
    return {'mode': 'offline-legacy-farm-detach', 'graphId': GRAPH_ID, 'name': GRAPH_NAME,
        'baselineGilSha256': BASELINE_SHA,
        'baselineGraphSha256': hashlib.sha256(old.SerializeToString()).hexdigest(),
        'expectedGraphSha256': hashlib.sha256(expected.SerializeToString()).hexdigest(),
        'expectedShape': {'nodes': 56, 'edges': 83, 'plannedValues': 55},
        'operations': [{'action': 'disconnect', 'fromNodeId': a, 'fromPortKind': 2,
                        'fromPortIndex': 0, 'toNodeId': b, 'toPortKind': 1,
                        'toPortIndex': 0} for a, b in EDGES],
        'dispatchable': False, 'gameModified': False, 'playtestVerified': False,
        'requires': ['User resumes live work and current level is freshly verified.',
                     'Native fixed-scope handler or verified binding replacement; graph is already bound.',
                     'New player graph and single Z control are fully configured before switching.',
                     'Switch in edit mode; no active planting timer is carried across migration.',
                     'Export and compare exact graph bytes before one reviewed native save.']}


def verify_graph(graph):
    expected = remove_exact_entries(baseline())
    if graph.SerializeToString() != expected.SerializeToString():
        raise ValueError('OLD_FARM_NOT_EXACT_THREE_EDGE_DETACH')
    return {'ok': True, 'graphId': GRAPH_ID, 'onlyRemovedEdges': list(EDGES),
            'allOtherGraphBytesPreserved': True, 'playtestVerified': False}


def verify_patch_export(path):
    _, graph = graph_at(path)
    return verify_graph(graph)
