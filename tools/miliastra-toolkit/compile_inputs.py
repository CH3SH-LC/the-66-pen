"""Compile structured AI arguments into real production CLI input artifacts."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime/miliastra-toolkit"


def obj(properties, required):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


UINT = {"type": "integer", "minimum": 0, "maximum": 4294967295}
INDEX = {"type": "integer", "minimum": 0, "maximum": 127}
VECTOR = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
PLACEMENT = obj({
    "template_id": UINT, "position": VECTOR, "rotation": VECTOR, "scale": VECTOR,
    "label": {"type": "string", "maxLength": 256},
}, ("template_id", "position", "scale"))
NODE = obj({"definitionId": UINT, "x": {"type": "integer"}, "y": {"type": "integer"}}, ("definitionId",))
EDGE = obj({
    "from": INDEX, "to": INDEX,
    "fromKind": {"type": "integer", "enum": [2, 4]}, "fromIndex": UINT,
    "toKind": {"type": "integer", "enum": [1, 3]}, "toIndex": UINT,
}, ("from", "to", "fromKind", "fromIndex", "toKind", "toIndex"))
TAGS = {
    "uint": UINT,
    "int": {"type": "integer", "minimum": -2147483648, "maximum": 2147483647},
    "float": {"type": "number", "minimum": -1e9, "maximum": 1e9},
    "bool": {"type": "boolean"},
    "string": {"type": "string", "maxLength": 1024},
    "vector3": {"type": "array", "minItems": 3, "maxItems": 3,
                "items": {"type": "number", "minimum": -1e9, "maximum": 1e9}},
}
LEAVES = [obj({tag: schema}, (tag,)) for tag, schema in TAGS.items() if tag != "vector3"]
TAGGED_VALUE = {"oneOf": [
    *[obj({tag: schema}, (tag,)) for tag, schema in TAGS.items()],
    obj({"list": {"type": "array", "maxItems": 64, "items": {"oneOf": [
        obj({tag: TAGS[tag]}, (tag,)) for tag in ("int", "uint", "float", "string")]}}}, ("list",)),
    obj({"dict": {"type": "array", "maxItems": 64, "items": obj({
        "key": {"oneOf": LEAVES}, "value": {"oneOf": LEAVES}}, ("key", "value"))}}, ("dict",)),
]}
VALUE = obj({
    "node": INDEX, "portIndex": UINT,
    "slot": {"type": "string", "enum": ["auto", "uint", "int", "enum", "float", "bool", "string", "vector3"]},
    "value": TAGGED_VALUE,
}, ("node", "portIndex", "slot", "value"))
SCHEMAS = {
    "scene.plan": obj({
        "placements": {"type": "array", "minItems": 1, "maxItems": 256, "items": PLACEMENT},
    }, ("placements",)),
    "graph.compile": obj({
        "name": {"type": "string", "pattern": "^MW_API_[A-Za-z0-9_]{1,48}$"},
        "graph_kind": {"type": "integer", "enum": [20000, 20001, 20002, 20007]},
        "nodes": {"type": "array", "minItems": 1, "maxItems": 128, "items": NODE},
        "edges": {"type": "array", "maxItems": 1024, "items": EDGE},
        "values": {"type": "array", "maxItems": 256, "items": VALUE},
    }, ("name", "graph_kind", "nodes")),
}


def production_source(api, name):
    tool = api.registry()[name]
    api.verify_tool_code(tool)
    return tool


def write_artifact(api, kind, payload, sources, extra):
    encoded = api.compact(payload).encode("utf-8")
    identity = hashlib.sha256(api.compact({"kind": kind, "payload": payload, "sources": sources, "metadata": extra}).encode()).hexdigest()
    folder = RUNTIME / "artifacts" / identity
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "plan.json"
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise api.ToolError("COMPILED_ARTIFACT_CONTENT_CONFLICT")
    result = {"ok": True, "kind": kind, "artifactId": identity, "plan_file": str(path),
              "sha256": api.sha(path), "bytes": len(encoded), "sources": sources,
              "nativeCalled": False, "runtimeVerified": False, **extra}
    manifest = folder / "manifest.json"
    if not manifest.exists():
        manifest.write_text(api.compact(result), encoding="utf-8")
    return result


def scene_plan(api, args):
    tool = production_source(api, "scene.create_batch")
    path = ROOT / tool["source"]
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_toolkit_scene_input_validator", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    normalized = module.normalize_placements(args["placements"])
    with api.db() as connection:
        for row in normalized:
            if not connection.execute("SELECT 1 FROM entities WHERE template_id=?", (row["template_id"],)).fetchone():
                raise api.ToolError("TEMPLATE_NOT_IN_CATALOG:" + str(row["template_id"]))
    payload = {"placements": args["placements"]}
    if len(api.compact(payload).encode("utf-8")) > module.MAX_PLAN_BYTES:
        raise api.ToolError("PLACEMENT_PLAN_EXCEEDS_PRODUCTION_LIMIT")
    return write_artifact(api, "scene-plan", payload,
                          {"validator": tool["source"], "validatorSha256": tool["sourceSha256"],
                           "catalogSha256": api.sha(api.DATA / "catalog.sqlite")},
                          {"placementCount": len(normalized), "nextTool": "scene.create_batch",
                           "nextArgument": "plan", "validatedBy": "scene_cli.normalize_placements",
                           "creationFeasibility": "requires-live-template-and-scene-preflight"})


def graph_compile(api, args):
    production_source(api, "node.recipe")
    author = production_source(api, "author.graph.build_plan")
    sys.path.insert(0, str(ROOT))
    from tools.node_workbench.catalog import Catalog
    from tools.node_workbench.recipes import compatible_edge, parameter_recipe
    from tools.authoring.author import validate_scalar_payload, validate_edge
    catalog = Catalog()
    kinds = args["graph_kind"]
    nodes = [{"definitionId": n["definitionId"], "x": n.get("x", 0), "y": n.get("y", 0)}
             for n in args["nodes"]]
    definitions = [catalog.require(kinds, node["definitionId"]) for node in nodes]
    edges, values = args.get("edges", []), args.get("values", [])
    generic_edges, seen_edges = [], set()
    for edge in edges:
        if max(edge["from"], edge["to"]) >= len(nodes) or edge["from"] == edge["to"]:
            raise api.ToolError("GRAPH_EDGE_NODE_REFERENCE_INVALID")
        frozen = api.compact(edge)
        if frozen in seen_edges:
            raise api.ToolError("GRAPH_DUPLICATE_EDGE")
        seen_edges.add(frozen)
        validate_edge({"fromNodeId": edge["from"], "toNodeId": edge["to"],
                       "fromPortKind": edge["fromKind"], "fromPortIndex": edge["fromIndex"],
                       "toPortKind": edge["toKind"], "toPortIndex": edge["toIndex"]})
        match = compatible_edge(catalog, kinds, nodes[edge["from"]]["definitionId"],
                                f'{edge["fromKind"]}:{edge["fromIndex"]}',
                                nodes[edge["to"]]["definitionId"], f'{edge["toKind"]}:{edge["toIndex"]}')
        if match["requiresNativeGenericResolution"]:
            generic_edges.append(edge)
    seen_values, unresolved = set(), []
    for value in values:
        node = value["node"]
        if node >= len(nodes):
            raise api.ToolError("GRAPH_VALUE_NODE_REFERENCE_INVALID")
        key = (node, value["portIndex"])
        if key in seen_values:
            raise api.ToolError("GRAPH_DUPLICATE_INPUT_VALUE")
        seen_values.add(key)
        port = next((p for p in definitions[node]["ports"] if p["kind"] == 3 and p["index"] == value["portIndex"]), None)
        if port is None:
            raise api.ToolError("GRAPH_INPUT_PORT_NOT_DECLARED")
        validate_scalar_payload(value["value"])
        def bounded_strings(data):
            if isinstance(data, str) and len(data.encode("utf-16-le")) // 2 > 1024:
                raise api.ToolError("GRAPH_STRING_EXCEEDS_NATIVE_UTF16_LIMIT")
            if isinstance(data, (dict, list)):
                for child in data.values() if isinstance(data, dict) else data:
                    bounded_strings(child)
        bounded_strings(value["value"])
        recipe = parameter_recipe(port)
        tag = next(iter(value["value"]))
        slot = value["slot"]
        if slot != "auto" and tag != ("uint" if slot == "enum" else slot):
            raise api.ToolError("GRAPH_VALUE_SLOT_PAYLOAD_MISMATCH")
        if recipe["status"] == "candidate-scalar-slot":
            if tag != recipe["payloadTag"]:
                raise api.ToolError("GRAPH_VALUE_DECLARED_STORAGE_MISMATCH")
            if recipe.get("enumValues") and value["value"][tag] not in {v["value"] for v in recipe["enumValues"]}:
                raise api.ToolError("GRAPH_ENUM_VALUE_NOT_DECLARED")
        else:
            unresolved.append({"node": node, "portIndex": value["portIndex"], "status": recipe["status"]})
    payload = {"nodes": nodes, "edges": edges, "values": values}
    envelope = {"op": "author-graph", "action": "build-plan", "id": "0" * 128, "nonce": "0" * 128,
                "name": args["name"], "graphId": 4294967295, "plan": payload}
    request_bytes = len(json.dumps(envelope, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    if request_bytes > 15500:
        raise api.ToolError("GRAPH_REQUEST_EXCEEDS_CONSERVATIVE_15500_BYTE_LIMIT")
    return write_artifact(api, "graph-plan", payload,
                          {"writer": author["source"], "writerSha256": author["sourceSha256"],
                           "nodeCatalogSha256": api.sha(ROOT / "data/node-workbench/catalog.json")},
                          {"name": args["name"], "graphKind": kinds, "nodes": len(nodes), "edges": len(edges),
                           "values": len(values), "requestBytesUpperBound": request_bytes,
                           "nextTool": "author.graph.build_plan", "nextArgument": "plan_file",
                           "requiresFreshEmptyGraph": True, "expectedNodeCount": 0,
                           "nativeGenericResolutionRequired": generic_edges,
                           "liveInputStorageRequired": unresolved, "mustReadLiveSlotsBeforeWrite": True})


def invoke(api, name, args, *, plan=False):
    api.validate(args, SCHEMAS[name])
    if plan:
        return {"ok": True, "mode": "plan", "tool": name, "arguments": args, "nativeCalled": False,
                "runtimeVerified": False, "artifactWritten": False}
    return scene_plan(api, args) if name == "scene.plan" else graph_compile(api, args)
