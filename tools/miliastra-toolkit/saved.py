"""Read, compare and index actual saved instances and graphs without game access."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime/miliastra-toolkit"
sys.path.insert(0, str(ROOT / "tools/beyond-save"))
import entity_geometry as geometry
import gil_container as gc


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def resolve(value):
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def snapshot(value, level_id):
    path = resolve(value)
    if path.suffix.lower() != ".gil":
        raise ValueError("GIL_EXTENSION_REQUIRED")
    if not path.is_file():
        raise ValueError("SAVE_NOT_FOUND:" + str(path))
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("SAVE_TOO_LARGE")
    raw = path.read_bytes()
    container = gc.decode_container(raw)
    if container.subtype != 2:
        raise ValueError("EXPECTED_LEVEL_GIL")
    level = gc.parse_level(container.payload, level_id)
    records = geometry.read_entity_records_blob(raw, str(path))
    entities = []
    ids = set()
    for record in records:
        if record.entity_id is None or record.entity_id in ids:
            raise ValueError("ENTITY_ID_MISSING_OR_DUPLICATED")
        ids.add(record.entity_id)
        transform = record.transform
        entities.append({"entityId": record.entity_id, "templateId": record.tag,
                         "position": list(transform.position.triple()) if transform else None,
                         "rotation": list(transform.rotation.triple()) if transform else None,
                         "scale": list(transform.scale.triple()) if transform else None,
                         "geometrySource": "root5.entry6.kind1.field11" if transform else "unknown",
                         "components": [{"group": c.group, "kind": c.kind, "payloadField": c.payload_field,
                                         "payloadBytes": c.payload_len} for c in record.components],
                         "recordSha256": digest(record.raw_bytes)})
    spec = importlib.util.spec_from_file_location("_toolkit_saved_graphs", ROOT / "tools/editor-bridge/audit-native-enums.py")
    graph_module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(graph_module)
    except ModuleNotFoundError as exc:
        if exc.name in ("google", "google.protobuf"):
            raise ValueError('SAVE_GRAPH_DEPENDENCY_MISSING: python -m pip install "protobuf>=5,<8"') from exc
        raise
    from miliastra_agent.parsers.entity_graph_bindings import parse_gil_entity_graph_bindings
    bindings = parse_gil_entity_graph_bindings(container.payload)
    graphs = []
    for group in graph_module.get_bytes_fields(container.payload, 10):
        for wrapper in graph_module.get_bytes_fields(group, 1):
            for graph_raw in graph_module.get_bytes_fields(wrapper, 1):
                graph = graph_module.pb.NodeGraph()
                graph.ParseFromString(graph_raw)
                rows = []
                for node in graph.nodes:
                    edges = []
                    for pin in node.pins:
                        for connection in pin.connections:
                            edges.append({"fromKind": pin.shell_sig.kind, "fromIndex": pin.shell_sig.index,
                                          "toNode": connection.target_node_index,
                                          "toKind": connection.target_pin_shell.kind,
                                          "toIndex": connection.target_pin_shell.index})
                    rows.append({"nodeId": node.index, "definitionId": node.shell_ref.runtime_id,
                                 "edges": edges, "serializedSha256": digest(node.SerializeToString())})
                graphs.append({"graphId": graph.identity.runtime_id, "name": graph.display_name,
                               "nodes": rows, "nodeCount": len(rows),
                               "edgeCount": sum(len(n["edges"]) for n in rows),
                               "boundEntityIds": [b.entity_id for b in bindings if b.graph_id == graph.identity.runtime_id],
                               "serializedSha256": digest(graph_raw), "runtimeVerified": False})
    if len({g["graphId"] for g in graphs}) != len(graphs):
        raise ValueError("GRAPH_ID_DUPLICATED")
    grouped = defaultdict(list)
    for field in gc.parse_fields(container.payload):
        grouped[field.number].append(field)
    fields = {str(number): {"bytes": len(gc.encode_fields(values)), "sha256": digest(gc.encode_fields(values))}
              for number, values in sorted(grouped.items())}
    if path.read_bytes() != raw:
        raise ValueError("SAVE_CHANGED_DURING_READBACK")
    return {"ok": True, "scope": "saved-file-content-only", "gil": str(path), "sha256": digest(raw),
            "bytes": len(raw), "levelId": level.level_id, "name": level.name,
            "entityCount": len(entities), "templateCount": len({e["templateId"] for e in entities}),
            "graphCount": len(graphs), "entities": entities, "graphs": graphs, "rootFields": fields,
            "nativeCalled": False, "nativeSaveVerified": False, "runtimeVerified": False}


def cache():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(RUNTIME / "observations.sqlite")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS observations(sha256 TEXT PRIMARY KEY,level_id INTEGER,source TEXT,
      entity_count INTEGER,graph_count INTEGER,payload TEXT);
    CREATE TABLE IF NOT EXISTS instances(observation TEXT,entity_id INTEGER,template_id INTEGER,
      x REAL,y REAL,z REAL,payload TEXT,PRIMARY KEY(observation,entity_id));
    CREATE INDEX IF NOT EXISTS instance_template ON instances(observation,template_id);
    CREATE TABLE IF NOT EXISTS graphs(observation TEXT,graph_id INTEGER,name TEXT,node_count INTEGER,
      payload TEXT,PRIMARY KEY(observation,graph_id));
    """)
    return connection


def capture(report):
    with cache() as con:
        identity = report["sha256"]
        con.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                    (identity, report["levelId"], report["gil"], report["entityCount"],
                     report["graphCount"], compact(report)))
        for entity in report["entities"]:
            xyz = entity["position"] or [None, None, None]
            con.execute("INSERT OR IGNORE INTO instances VALUES (?,?,?,?,?,?,?)",
                        (identity, entity["entityId"], entity["templateId"], *xyz, compact(entity)))
        for graph in report["graphs"]:
            con.execute("INSERT OR IGNORE INTO graphs VALUES (?,?,?,?,?)",
                        (identity, graph["graphId"], graph["name"], graph["nodeCount"], compact(graph)))
    return {"ok": True, "observation": identity, "database": str(RUNTIME / "observations.sqlite"),
            **{key: report[key] for key in ("levelId", "entityCount", "graphCount", "gil", "bytes")},
            "nativeCalled": False, "runtimeVerified": False}


def diff(before, after):
    a, b = {e["entityId"]: e for e in before["entities"]}, {e["entityId"]: e for e in after["entities"]}
    ga, gb = {g["graphId"]: g for g in before["graphs"]}, {g["graphId"]: g for g in after["graphs"]}
    changed_fields = [key for key in sorted(set(before["rootFields"]) | set(after["rootFields"]), key=int)
                      if before["rootFields"].get(key) != after["rootFields"].get(key)]
    return {"ok": True, "scope": "saved-file-content-only", "levelId": after["levelId"],
            "beforeSha256": before["sha256"], "afterSha256": after["sha256"],
            "saveContentChanged": before["sha256"] != after["sha256"], "changedRootFields": changed_fields,
            "entities": {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
                         "changed": sorted(i for i in a.keys() & b.keys() if a[i] != b[i])},
            "graphs": {"added": sorted(gb.keys() - ga.keys()), "removed": sorted(ga.keys() - gb.keys()),
                       "changed": sorted(i for i in ga.keys() & gb.keys() if ga[i] != gb[i])},
            "nativeCalled": False, "nativeSaveVerified": False, "runtimeVerified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "capture"):
        p = sub.add_parser(action)
        p.add_argument("--gil", type=Path, required=True)
        p.add_argument("--level-id", type=int, required=True)
        if action == "inspect":
            p.add_argument("--entity-id", type=int, action="append")
            p.add_argument("--template-id", type=int)
            p.add_argument("--offset", type=int, default=0)
            p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("diff")
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--level-id", type=int, required=True)
    p = sub.add_parser("instances")
    p.add_argument("--observation", required=True)
    p.add_argument("--template-id", type=int)
    p.add_argument("--entity-id", type=int)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("graphs")
    p.add_argument("--observation", required=True)
    p.add_argument("--graph-id", type=int)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    try:
        if hasattr(args, "limit") and not (1 <= args.limit <= 500 and args.offset >= 0):
            raise ValueError("PAGE_REQUIRES_LIMIT_1_TO_500_AND_NONNEGATIVE_OFFSET")
        if args.action == "diff":
            result = diff(snapshot(args.before, args.level_id), snapshot(args.after, args.level_id))
        elif args.action in ("instances", "graphs"):
            if not re_valid_hash(args.observation):
                raise ValueError("OBSERVATION_SHA256_REQUIRED")
            with cache() as con:
                exists = con.execute("SELECT level_id FROM observations WHERE sha256=?", (args.observation,)).fetchone()
                if exists is None:
                    raise ValueError("OBSERVATION_NOT_FOUND")
                where, params = ["observation=?"], [args.observation]
                if args.action == "graphs":
                    if args.graph_id is not None:
                        where.append("graph_id=?")
                        params.append(args.graph_id)
                    sql = " AND ".join(where)
                    count = con.execute("SELECT count(*) FROM graphs WHERE " + sql, params).fetchone()[0]
                    if args.graph_id is not None and count != 1:
                        raise ValueError("GRAPH_NOT_IN_OBSERVATION")
                    rows = con.execute("SELECT payload FROM graphs WHERE " + sql + " ORDER BY graph_id LIMIT ? OFFSET ?",
                                       params + [args.limit, args.offset])
                    graphs = [json.loads(row[0]) for row in rows]
                    if args.graph_id is None:
                        graphs = [{k: v for k, v in g.items() if k != "nodes"} for g in graphs]
                    result = {"ok": True, "observation": args.observation, "levelId": exists[0],
                              "total": count, "graphs": graphs, "nativeCalled": False}
                    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
                    return 0
                for key in ("template_id", "entity_id"):
                    if getattr(args, key) is not None:
                        where.append(key + "=?")
                        params.append(getattr(args, key))
                sql = " AND ".join(where)
                count = con.execute("SELECT count(*) FROM instances WHERE " + sql, params).fetchone()[0]
                rows = con.execute("SELECT payload FROM instances WHERE " + sql + " ORDER BY entity_id LIMIT ? OFFSET ?",
                                   params + [args.limit, args.offset])
                result = {"ok": True, "observation": args.observation, "levelId": exists[0], "total": count,
                          "entities": [json.loads(row[0]) for row in rows], "nativeCalled": False}
        else:
            report = snapshot(args.gil, args.level_id)
            if args.action == "capture":
                result = capture(report)
            else:
                entities = report["entities"]
                if args.entity_id:
                    found = {e["entityId"] for e in entities}
                    missing = set(args.entity_id) - found
                    if missing:
                        raise ValueError("ENTITY_NOT_IN_SAVE:" + ",".join(map(str, sorted(missing))))
                    entities = [e for e in entities if e["entityId"] in args.entity_id]
                if args.template_id is not None:
                    entities = [e for e in entities if e["templateId"] == args.template_id]
                result = dict(report, matchedEntities=len(entities), offset=args.offset,
                              entities=entities[args.offset:args.offset + args.limit],
                              graphs=[{k: v for k, v in g.items() if k != "nodes"} for g in report["graphs"]])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "nativeCalled": False,
                          "runtimeVerified": False}, ensure_ascii=False))
        return 2


def re_valid_hash(value):
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


if __name__ == "__main__":
    raise SystemExit(main())
