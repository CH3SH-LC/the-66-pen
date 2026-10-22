#!/usr/bin/env python3
"""Read-only per-object-domain readback of ONE saved level GIL (D23.01.01).

WHY THIS FILE EXISTS
--------------------
Leaf D23.01.01 asks, per object domain that actually participated in S1-S3, that the
domain's objects be shown to EXIST in the bytes a real native save wrote
(positiveCheck: "请求ID关联真实保存回包，各域对象在落盘语义中存在；无该域对象则该域不得通过").

The tree already knows how to read each of the three participating domains SEPARATELY,
and each reader is proven against the same saved file:

  entity   ``tools/game-executor/verify-created-save.py`` -> ``miliastra_agent.parsers
           .entities.parse_payload`` (used by ``verify_saved.py`` and
           ``native_reopen_acceptance.formal_content``)
  graph    ``tools/editor-bridge/audit-native-enums.py`` -> ``load_graphs`` (the same
           NodeGraph protobuf walk ``formal_content`` uses)
  binding  ``miliastra_agent.parsers.entity_graph_bindings
           .parse_gil_entity_graph_bindings``

What was missing is a single reader that answers the four domains AT ONCE, for an
ARBITRARY level id, with no create-shaped assumption (``formal_content`` is pinned to
level 1073741839 and requires a create's exact node/edge shape).  ``verify_saved.py`` is
the closest thing, but it is hard-wired to "exactly one event node and one print node"
and to one entity, and its own inventory row (``tools/authoring/INTERFACE-INVENTORY.md``
:49) is marked ``partial`` with "需计划驱动通用读回".

This module is that generic readback.  It is a MEASURING INSTRUMENT: it opens the file
read-only, reports which ids of each domain the bytes hold, and refuses -- by name --
anything that is not a readable GIL of the level it was asked about.

WHAT IT IS NOT
--------------
* It is not a verdict.  It returns facts; the per-domain verdict belongs to
  ``backend/save_domain_coverage.py``, which also binds the reply and the participation
  roster.
* It does not read the live game account and does not write anything anywhere: only the
  path it is handed is opened, and only stdout is written.
* It has no reader for the ``component`` / ``resource`` domains -- no such saved-GIL
  reader exists in this tree -- so it reports them as ``unreadable`` rather than as an
  empty list that a caller could mistake for "participated but empty".

Run under the pinned content interpreter (``config/save-content-interpreter.lock.json``):
``google.protobuf`` and ``miliastra_agent`` are not importable from the MCP venv.

    python -B tools/game-executor/read_saved_domains.py --gil <path> --level-id <int>

Exit 0 = readback produced; 2 = a named refusal (never a partial answer).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The three domains this tree can resolve from the saved bytes, and the two it cannot.
READABLE_DOMAINS = ('entity', 'graph', 'binding')
UNREADABLE_DOMAINS = ('component', 'resource')

#: Where the parsers live.  ``audit-native-enums`` inserts this itself; doing it here too
#: keeps the reader runnable when it is the FIRST thing loaded (the pin's own probe relies
#: on the same root being reachable).
PARSER_SOURCE_REL = 'third_party/auto-miliastra/src'

#: The GIL container framing, identical to ``audit-native-enums.load_graphs``.
GIL_MAGIC = 0x326
GIL_TRAILER = 0x679
GIL_KIND = 2
MAX_GIL_BYTES = 1 << 28


class ReadbackRefusal(ValueError):
    """A named refusal; the reader prints nothing but this and exits non-zero."""

    def __init__(self, code, detail):
        super().__init__('%s: %s' % (code, detail))
        self.code, self.detail = code, detail

    def as_json(self):
        return {'ok': False, 'error': {'code': self.code, 'detail': self.detail}}


def _load_module(name, path):
    if not Path(path).is_file():
        raise ReadbackRefusal('READER_MISSING', 'the reader %s is not on disk' % path)
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _parser_root():
    root = ROOT / PARSER_SOURCE_REL
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def binding_key(pair):
    """One canonical binding id: ``"<entityId>-><graphId>"``.

    A binding is a pair, so it has no single id in the format; the key is derived HERE,
    once, so the reader and every consumer compare the same string.
    """
    return '%s->%s' % (int(pair[0]), int(pair[1]))


def read_domains(gil_path, level_id):
    """``{entity: [...], graph: [...], binding: [...]}`` from one saved GIL, or a refusal.

    Every domain list is sorted and deduplicated so two readbacks of identical bytes are
    comparable byte for byte.  The return also names the readers actually used, so a
    report can be read without re-deriving which parser produced a row.
    """
    gil_path = Path(gil_path)
    if not gil_path.is_file():
        raise ReadbackRefusal('GIL_MISSING', '%s is not on disk' % gil_path)
    if isinstance(level_id, bool) or not isinstance(level_id, int) or level_id <= 0:
        raise ReadbackRefusal('LEVEL_ID_INVALID', 'level id %r is not a positive int' % (level_id,))

    _parser_root()
    reader = _load_module('saved_domain_entity_reader',
                          ROOT / 'tools/game-executor/verify-created-save.py')
    graphs = _load_module('saved_domain_graph_reader',
                          ROOT / 'tools/editor-bridge/audit-native-enums.py')
    try:
        from miliastra_agent.parsers.entities import parse_payload
        from miliastra_agent.parsers.entity_graph_bindings import (
            parse_gil_entity_graph_bindings)
    except ImportError as error:                       # pragma: no cover - pin-dependent
        raise ReadbackRefusal(
            'PARSERS_UNIMPORTABLE',
            '%s; this reader must run under the pinned content interpreter '
            '(config/save-content-interpreter.lock.json)' % error) from None

    data = gil_path.read_bytes()
    if not 0 < len(data) <= MAX_GIL_BYTES:
        raise ReadbackRefusal('GIL_SIZE', '%s is %d bytes' % (gil_path, len(data)))
    length, version, magic, kind, payload_length = struct.unpack('>5I', data[:20])
    trailer = struct.unpack('>I', data[-4:])[0]
    if not (length == len(data) - 4 and version == 1 and magic == GIL_MAGIC
            and kind == GIL_KIND and payload_length == len(data) - 24
            and trailer == GIL_TRAILER):
        raise ReadbackRefusal('GIL_NOT_A_GIL',
                              '%s does not carry the level-file container framing' % gil_path)
    payload = data[20:-4]
    observed_level = reader.scalar(payload, 1)
    if observed_level != level_id:
        raise ReadbackRefusal('GIL_LEVEL_MISMATCH',
                              '%s is the file of level %r, not level %r'
                              % (gil_path, observed_level, level_id))

    rows = parse_payload(payload, file_type=2)
    entity_ids = sorted({int(row.entity_id) for row in rows})
    templates = sorted({int(row.template_id) for row in rows if row.template_id})

    _, decoded_graphs = graphs.load_graphs(gil_path)
    graph_ids = sorted({int(g.identity.runtime_id) for g in decoded_graphs})
    display_names = {int(g.identity.runtime_id): g.display_name for g in decoded_graphs}

    binding_keys = sorted({binding_key((b.entity_id, b.graph_id))
                           for b in parse_gil_entity_graph_bindings(payload)})

    return {
        'ok': True,
        'gil': str(gil_path),
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': len(data),
        'levelId': level_id,
        'domains': {'entity': entity_ids, 'graph': graph_ids, 'binding': binding_keys},
        'unreadableDomains': list(UNREADABLE_DOMAINS),
        'detail': {
            'entityCount': len(entity_ids),
            'templates': templates,
            'graphDisplayNames': {str(k): v for k, v in sorted(display_names.items())},
            'bindingCount': len(binding_keys),
        },
        'readers': {
            'entity': 'tools/game-executor/verify-created-save.py + '
                      'miliastra_agent.parsers.entities.parse_payload',
            'graph': 'tools/editor-bridge/audit-native-enums.py load_graphs',
            'binding': 'miliastra_agent.parsers.entity_graph_bindings'
                       '.parse_gil_entity_graph_bindings',
        },
        'note': 'read-only readback of one saved GIL; a fact source, not a verdict',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--gil', type=Path, required=True, help='the saved level .gil to read')
    parser.add_argument('--level-id', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = read_domains(args.gil, args.level_id)
    except ReadbackRefusal as refusal:
        print(json.dumps(refusal.as_json(), ensure_ascii=False))
        return 2
    except Exception as error:                          # noqa: BLE001 - a failure is a datum
        print(json.dumps({'ok': False, 'error': {
            'code': 'READBACK_FAILED',
            'detail': '%s: %s' % (type(error).__name__, error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
