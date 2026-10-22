"""Offline evidence validator for one fixed 1839 reopen roundtrip.

No process access, method call, replay, lease release, or helper integration.
Raw receipts are decoded again. A returned call, 1022, or a vanished task cannot
establish load. Formal parameter-tag mapping is deliberately a separate claim.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import os
from datetime import datetime

# The helper executes -B -I -S. Add only the fixed local module and parser
# package root; never execute sitecustomize, .pth files or pydantic plugins.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path(sys.executable).resolve().parent / "Lib/site-packages"))
os.environ["PYDANTIC_DISABLE_PLUGINS"] = "__all__"
LEVEL = 1073741840
FORMAL_RELATIVE = f"Beyond_Local_Save_Level/{LEVEL}/{LEVEL}.gil"
MAX_JSON = 32 * 1024 * 1024
import native_profiles as profiles
import native_write_review as review_api
import build_readonly_profile as readonly
import native_level_catalog as catalog_api
import native_lifecycle_type as type_api
import native_scheduler_coroutines as scheduler_api
import native_reopen_guards as guards_api


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_read(path):
    data = Path(path).read_bytes()
    require(0 < len(data) <= MAX_JSON, "EVIDENCE_SIZE")
    def pairs(rows):
        result = {}
        for k, v in rows:
            require(k not in result, "DUPLICATE_JSON_KEY:" + k)
            result[k] = v
        return result
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def utc(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(value.tzinfo is not None, "UTC_REQUIRED")
    return value


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def checked_path(entry, *, runtime=True):
    require(type(entry) is dict and set(entry) == {"path", "sha256"}, "ARTIFACT_REFERENCE")
    p = Path(entry["path"]).resolve()
    require(not runtime or p.is_relative_to(ROOT / ".runtime"), "EVIDENCE_OUTSIDE_RUNTIME")
    require(re.fullmatch("[0-9a-f]{64}", entry["sha256"]) is not None and sha(p) == entry["sha256"], "ARTIFACT_HASH:" + p.name)
    return p


def unique(rows, key, label):
    require(type(rows) is list, label + "_LIST")
    result = {}
    for row in rows:
        k = row[key]
        require(type(k) is int and k >= 0 and k not in result, label + "_IDENTITY")
        result[k] = row
    return result


def canonical_tree(value):
    """Compare the entire captured value/reference graph, ignoring only local IDs.

    Object IDs encode identity within this capture, not process addresses. Every
    reference must resolve; field order is not significant, sequence order is.
    """
    objects = {}
    budget = [0]
    def collect(v, depth=0):
        budget[0] += 1
        require(depth <= 96 and budget[0] <= 65536 * 16, "RAW_TREE_BOUND")
        if isinstance(v, dict):
            require(not any(k in v for k in ("error", "truncated", "unavailable")), "RAW_TREE_INCOMPLETE")
            if "objectId" in v and v["objectId"] is not None:
                i = v["objectId"]
                require(type(i) is int and i > 0 and i not in objects, "RAW_OBJECT_ID")
                objects[i] = v
            for child in v.values(): collect(child, depth + 1)
        elif isinstance(v, list):
            for child in v: collect(child, depth + 1)
        elif isinstance(v, float): require(math.isfinite(v), "RAW_NONFINITE")
        else: require(v is None or type(v) in (str, int, bool), "RAW_SCALAR")
    collect(value)
    def ordering_key(value):
        # Structural key only for explicitly unordered captures. Reference IDs
        # are local to each key; the final walk still preserves shared aliases.
        local = {}
        def key(v, depth=0):
            require(depth <= 128, "RAW_SET_KEY_DEPTH")
            if isinstance(v, dict):
                if "refId" in v:
                    require(set(v) == {"refId"} and v["refId"] in objects, "RAW_DANGLING_REFERENCE")
                    return key(objects[v["refId"]], depth + 1)
                if v.get("objectId") is not None:
                    i = v["objectId"]
                    if i in local: return {"ref":local[i]}
                    local[i] = len(local) + 1
                    v = dict(v, objectId=local[i])
                result = {}
                for name in sorted(v):
                    child = v[name]
                    if name == "fields": child = sorted(child, key=lambda x:(x["declaringType"],x["name"]))
                    result[name] = key(child, depth + 1)
                return result
            if isinstance(v, list): return [key(x, depth + 1) for x in v]
            return v
        return json.dumps(key(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    seen = {}
    def walk(v, depth=0):
        require(depth <= 128, "RAW_REFERENCE_DEPTH")
        if isinstance(v, dict):
            if "refId" in v:
                require(set(v) == {"refId"} and v["refId"] in objects, "RAW_DANGLING_REFERENCE")
                return walk(objects[v["refId"]], depth + 1)
            if "objectId" in v and v["objectId"] is not None:
                identity = v["objectId"]
                if identity in seen: return {"ref": seen[identity]}
                seen[identity] = len(seen) + 1
                v = dict(v, objectId=seen[identity])
            out = {}
            for key in sorted(v):
                child = v[key]
                if key == "fields":
                    require(isinstance(child, list), "RAW_FIELD_LIST")
                    keys = [(x["declaringType"], x["name"]) for x in child]
                    require(len(keys) == len(set(keys)), "RAW_DUPLICATE_FIELD")
                    child = sorted(child, key=lambda x: (x["declaringType"], x["name"]))
                if key == "items" and v.get("unordered") is True:
                    require(isinstance(child, list), "RAW_SET_ITEMS")
                    keyed = [(ordering_key(x), x) for x in child]
                    require(len({k for k,_ in keyed}) == len(keyed), "RAW_UNORDERED_AMBIGUOUS_KEY")
                    child = [x for _,x in sorted(keyed, key=lambda pair:pair[0])]
                out[key] = walk(child, depth + 1)
            return out
        if isinstance(v, list): return [walk(x, depth + 1) for x in v]
        return v
    if isinstance(value, dict) and set(value) == {"root", "objects"}:
        require(isinstance(value["objects"], list), "RAW_OBJECT_TABLE")
        canonical = walk(value["root"])
        require(set(seen) == set(objects), "RAW_UNREACHABLE_OBJECT")
        return canonical
    return walk(value)


def normalized_edge(src, dst):
    a = (int(src["nodeId"]), int(src["kind"]), int(src["index"]))
    b = (int(dst["nodeId"]), int(dst["kind"]), int(dst["index"]))
    require(a[1] in (1, 2, 3, 4) and b[1] in (1, 2, 3, 4), "UNMAPPED_EDGE_KIND")
    if a[1] in (1, 3): a, b = b, a
    require((a[1], b[1]) in ((2, 1), (4, 3)), "EDGE_DIRECTION")
    return (*a, *b)


def formal_content(path, *, expected_level=LEVEL):
    """Use the existing GIL entity/binding and NodeGraph protobuf parsers.

    ``expected_level`` is the level id the recording at ``path`` was made at.  The
    live reopen path leaves it at the reviewed ``LEVEL`` pin (``FORMAL_RELATIVE``);
    an offline recording made while a different level was open states its own id
    explicitly instead of being refused.  The check itself is never relaxed: the
    save's field 1 must equal the level the caller declares for it.
    """
    reader = module("_reopen_gil_entities", ROOT / "tools/game-executor/verify-created-save.py")
    graphs = module("_reopen_gil_graphs", ROOT / "tools/editor-bridge/audit-native-enums.py")
    container = module("_reopen_gil_container", ROOT / "tools/beyond-save/gil_container.py")
    from miliastra_agent.parsers.entities import parse_payload
    from miliastra_agent.parsers.entity_graph_bindings import parse_gil_entity_graph_bindings
    from google.protobuf.json_format import MessageToDict
    data = Path(path).read_bytes()
    c = container.decode_container(data)
    require(c.subtype == 2, "FORMAL_NOT_GIL")
    payload = data[20:-4]
    require(reader.scalar(payload, 1) == expected_level, "FORMAL_LEVEL")
    records = reader.entity_records(payload)
    rows = parse_payload(payload, file_type=2)
    require(len(rows) == len(records) and len({x.entity_id for x in rows}) == len(rows), "FORMAL_ENTITY_COMPLETENESS")
    entities = {}
    for e in rows:
        require(e.entity_id in records, "FORMAL_ENTITY_RECORD_MISSING")
        # The parser prefers record field 8. The editor/native config reference
        # corresponds to the distinct record field 2 / inner field 1.
        reference_id = reader.scalar(reader.one(records[e.entity_id][0], 2), 1)
        entities[e.entity_id] = dict(id=e.entity_id, templateId=e.template_id,
            configurationReferenceId=reference_id,
            transform=reader.target_geometry(records[e.entity_id][0]),
            rawRecordSha256=hashlib.sha256(records[e.entity_id][0]).hexdigest())
    _, gs = graphs.load_graphs(Path(path))
    result = {}
    for g in gs:
        gid = g.identity.runtime_id
        require(gid > 0 and gid not in result, "FORMAL_GRAPH_ID")
        nodes, edges, parameters = {}, set(), {}
        for n in g.nodes:
            require(n.index not in nodes, "FORMAL_DUPLICATE_NODE")
            nodes[n.index] = n.shell_ref.runtime_id
            parameters[n.index] = MessageToDict(n, preserving_proto_field_name=True,
                                                use_integers_for_enums=True)
            for p in n.pins:
                src = dict(nodeId=n.index, kind=p.shell_sig.kind, index=p.shell_sig.index)
                for link in p.connections:
                    edges.add(normalized_edge(src, dict(nodeId=link.target_node_index,
                        kind=link.target_pin_shell.kind, index=link.target_pin_shell.index)))
        require(all(x[0] in nodes and x[3] in nodes for x in edges), "FORMAL_DANGLING_EDGE")
        result[gid] = dict(id=gid, nodes=nodes, edges=sorted(edges), parameters=parameters,
                           protobufSha256=hashlib.sha256(g.SerializeToString(deterministic=True)).hexdigest())
    bindings = parse_gil_entity_graph_bindings(payload)
    pairs = [(b.entity_id, b.graph_id) for b in bindings]
    require(len(pairs) == len(set(pairs)) and all(e in entities and g in result for e, g in pairs), "FORMAL_BINDINGS")
    return dict(levelId=expected_level, entities=entities, graphs=result, bindings=sorted(pairs),
                sha256=hashlib.sha256(data).hexdigest(), parameterMappingVerified=False)


def read_account(path, *, formal_relative=FORMAL_RELATIVE):
    manifest = json_read(path)
    root = Path(manifest["backup"]).resolve()
    require(root.is_relative_to(ROOT / ".runtime") and root.is_dir(), "ACCOUNT_IMMUTABLE_COPY_REQUIRED")
    rows = manifest["files"]
    result = {}
    for row in rows:
        rel = row["relativePath"]
        pure = PurePosixPath(rel)
        require(str(pure) == rel and not pure.is_absolute() and ".." not in pure.parts and "\\" not in rel, "ACCOUNT_PATH")
        require(rel.casefold() not in result, "ACCOUNT_DUPLICATE_PATH")
        f = (root / rel).resolve()
        require(f.is_relative_to(root) and f.is_file() and not f.is_symlink(), "ACCOUNT_FILE")
        require(type(row["bytes"]) is int and f.stat().st_size == row["bytes"] and sha(f) == row["sha256"], "ACCOUNT_HASH:" + rel)
        result[rel.casefold()] = (row["bytes"], row["sha256"])
    actual = {f.relative_to(root).as_posix().casefold() for f in root.rglob("*") if f.is_file()}
    require(actual == set(result) and manifest["fileCount"] == len(result) and manifest["totalBytes"] == sum(x[0] for x in result.values()), "ACCOUNT_COMPLETE_ENUMERATION")
    require(formal_relative.casefold() in result and "beyond_local_save_player.gip" in result, "ACCOUNT_REQUIRED_FILES")
    return dict(rows=result, manifest=manifest, formal=root / formal_relative)


def decode_action(record, prepared, context):
    require(record.get("scope") == "REVIEWED_REOPEN_ACTION" and record.get("transportOk") is True, "ACTION_SCOPE")
    raw = bytes.fromhex(record["reopenActionHex"])
    require(len(raw) == 104 and record["reopenActionBytes"] == 104, "ACTION_ABI_SIZE")
    size, version, action, status = struct.unpack_from("<4I", raw)
    invocation, entry, manager, target = struct.unpack_from("<4Q", raw, 16)
    level, preflight, route_before, route_after = struct.unpack_from("<4I", raw, 48)
    call = struct.unpack_from("<9I", raw, 64)
    require((size, version, action, status) == (104, 1, 4, 7) and record["reopenActionStatus"] == status and struct.unpack_from("<I", raw, 100)[0] == 0, "ACTION_NOT_RETURNED")
    definitions = prepared["nativeDefinitions"]
    nonce = definitions["HR_NONCE"]
    nonce = int(nonce, 0) if isinstance(nonce, str) else nonce
    require(type(nonce) is int and 0 < nonce < 2**64 and invocation == nonce, "ACTION_NONCE")
    require((level, preflight, route_before, route_after) == (LEVEL, 1, 1, 1), "ACTION_PREFLIGHT_ROUTE")
    require(call == (36, 1, 2, 1, 1, 0, 1, 0, 0), "ACTION_CALL_CONTRACT")
    require(entry == int(context["pointers"]["moduleBase"], 16) + 0x13564e90, "ACTION_ENTRY")
    cat = context["levelCatalog"]
    require(manager == int(cat["pointers"]["levelManager"], 16) and [x["record"] for x in cat["levels"] if x["id"] == LEVEL] == [target], "ACTION_CURRENT_RECORD")
    session = prepared["session"]
    require(record.get("pid") == session["pid"] and record.get("tid") == session["tid"] and record.get("callbackCount") == 1 and record.get("activeCallbacks") == 0 and record.get("unhooked") is True, "ACTION_HOOK_IDENTITY_CLEANUP")
    require(record.get("businessPending") is True and record.get("reopenVerified") is False and record.get("persistenceVerified") is False, "ACTION_PENDING_BOUNDARY")
    return dict(invocation=invocation, hookCleanupVerified=True, callReturned=True)


def load_progress(before, post, followup=None):
    require(before.get("ok") is True and post.get("ok") is True and before.get("logicalListComplete") is True and post.get("logicalListComplete") is True, "LOAD_SCHEDULER_INCOMPLETE")
    require(before["counts"]["targetCount"] == 0, "LOAD_PREEXISTING_TARGET")
    safe = ("null_handle", "released_holder", "other_class", "other_owner")
    require(all(r["classification"] in safe for r in before["rows"]), "LOAD_BEFORE_UNKNOWN_REFERENCE")
    for field in ("moduleBase", "global", "lifecycleOwner", "targetClass", "classSlot", "coroutineClass"):
        require(before["pointers"][field] == post["pointers"][field], "LOAD_ROOT_CHANGED:" + field)
    targets = [r for r in post["rows"] if r["classification"] == "target_iterator"]
    require(len(targets) == 1 and post["uniqueTargetIterators"] == 1 and post["duplicateNonNullHandles"] == 0, "LOAD_NOT_UNIQUE_NEW_TARGET")
    target = targets[0]
    for field in ("handle", "holder", "iterator"):
        require(target[field] not in {r[field] for r in before["rows"]}, "LOAD_PREEXISTING_" + field.upper())
    require(type(target["state"]) is int, "LOAD_INITIAL_TARGET_STAGE")
    if target["state"] not in (4, 5, 6, 7) and followup is not None:
        require(followup.get("ok") is True and followup.get("logicalListComplete") is True, "LOAD_FOLLOWUP_INCOMPLETE")
        for field in ("moduleBase", "global", "lifecycleOwner", "targetClass", "classSlot", "coroutineClass"):
            require(post["pointers"][field] == followup["pointers"][field], "LOAD_FOLLOWUP_ROOT_CHANGED")
        later = [r for r in followup["rows"] if r["classification"] == "target_iterator"]
        require(len(later) == 1 and all(later[0][k] == target[k] for k in ("handle", "holder", "iterator", "iteratorClass", "iteratorOwner")), "LOAD_FOLLOWUP_NOT_SAME_INSTANCE")
        target = later[0]
    require(target["stageObserved"] is True and target["state"] in (4, 5, 6, 7), "LOAD_STAGE_BEFORE_MODEL_RETURN")
    return dict(loadOccurred=True, iterator=target["iterator"], handle=target["handle"], state=target["state"],
                basis="single-request-same-callback-new-target-after-77cac00-return", completionVerified=False)



def decode_observation(record, context, invocation, post):
    encoded = record.get("reopenObservationHex")
    require(isinstance(encoded, str) and len(encoded) == 224 and re.fullmatch("[0-9a-fA-F]+", encoded) is not None and record.get("reopenObservationBytes") == 112, "OBSERVATION_ABI_SIZE")
    raw = bytes.fromhex(encoded)
    names = ("size", "version", "status", "flags", "invocation", "startTick", "endTick", "handle", "holder", "iterator", "iteratorClass", "owner", "requested", "completed", "callbacks", "rejected", "proofSequence", "lastSnapshotStatus", "overflow", "reserved")
    h = dict(zip(names, struct.unpack("<IIiI8Q4i4I", raw)))
    require(h["size"] == 112 and h["version"] == 1 and record.get("reopenObservationStatus") == h["status"], "OBSERVATION_ABI_VERSION")
    require(h["status"] in (2, 4), "LOAD_OBSERVATION_NOT_PROVEN:" + str(h["status"]))
    require(h["flags"] == 3 and h["invocation"] == invocation and h["rejected"] == h["overflow"] == h["reserved"] == 0, "OBSERVATION_NONCE_FLAGS_OR_REJECTION")
    require(0 < h["startTick"] <= h["endTick"] and h["endTick"] - h["startTick"] < 10000 and 0 <= h["completed"] == h["callbacks"] <= h["requested"] <= 200, "OBSERVATION_BOUND")
    require(post.get("ok") is True and post["counts"]["targetCount"] == 1, "OBSERVATION_INITIAL_TARGET")
    candidates = [r for r in post["rows"] if r["classification"] == "target_iterator"]
    require(len(candidates) == 1, "OBSERVATION_INITIAL_UNIQUE")
    candidate = candidates[0]
    for native, field in (("handle", "handle"), ("holder", "holder"), ("iterator", "iterator"), ("iteratorClass", "iteratorClass"), ("owner", "iteratorOwner")):
        require(h[native] == int(candidate[field], 16), "OBSERVATION_CANDIDATE_IDENTITY:" + field)
    def snapshot(prefix):
        value = record.get(prefix + "Hex")
        require(isinstance(value, str) and len(value) == scheduler_api.SCHEDULER_COROUTINES_BYTES * 2 and re.fullmatch("[0-9a-fA-F]+", value) is not None and record.get(prefix + "Bytes") == scheduler_api.SCHEDULER_COROUTINES_BYTES, "OBSERVATION_SNAPSHOT_SIZE:" + prefix)
        data = bytes.fromhex(value)
        require(record.get(prefix + "Status") == struct.unpack_from("<I", data, 8)[0], "OBSERVATION_SNAPSHOT_STATUS:" + prefix)
        return data
    proof_raw = snapshot("followupSchedulerCoroutines")
    last_raw = snapshot("lastObservationSchedulerCoroutines")
    require(h["lastSnapshotStatus"] == record["lastObservationSchedulerCoroutinesStatus"], "OBSERVATION_LAST_STATUS")
    before = context["schedulerCoroutines"]
    if h["status"] == 2:
        require(h["requested"] == h["completed"] == h["callbacks"] == h["proofSequence"] == 0 and not any(proof_raw) and not any(last_raw), "OBSERVATION_INITIAL_ONLY_FIELDS")
        progress = load_progress(before, post)
    else:
        require(candidate["state"] not in (4, 5, 6, 7) and 1 <= h["proofSequence"] <= h["completed"], "OBSERVATION_PROOF_SEQUENCE")
        derived = dict(record)
        for suffix in ("Hex", "Bytes", "Status"):
            derived["schedulerCoroutines" + suffix] = record["followupSchedulerCoroutines" + suffix]
        proof = scheduler_api.decode(derived, context, scheduler_api.load_profile())
        progress = load_progress(before, post, proof)
    progress.update(observationStatus=h["status"], proofSequence=h["proofSequence"], observationCallbacks=h["callbacks"],
        elapsedMs=h["endTick"]-h["startTick"], source="same-nonce-same-mapping-bounded-callback-observation",
        proofSnapshotSha256=hashlib.sha256(proof_raw).hexdigest(), lastSnapshotSha256=hashlib.sha256(last_raw).hexdigest())
    return progress

def editor_content(doc):
    shared = doc.get("schemaVersion") == 2
    expected_scope = "materialized-editor-business-fields-and-retained-initialization" + ("-shared-graph" if shared else "")
    require(doc.get("schemaVersion") in (1, 2) and doc.get("levelId") == LEVEL and doc.get("scope") == expected_scope, "EDITOR_SCOPE")
    require(all(doc.get(k) is True for k in ("ok", "complete", "captureComplete", "stableReadback")) and doc.get("truncated") is False and doc.get("errorCount") == 0, "EDITOR_INCOMPLETE")
    require(all(doc.get(k) is False for k in ("arbitraryGettersInvoked", "nativeSerializerInvoked", "nativeConstructorsInvoked", "sentToGame")), "EDITOR_NOT_READONLY")
    content = doc["content"]
    require(content["entityCount"] == len(content["entities"]) <= 128 and content["graphCount"] == len(content["graphs"]) <= 128, "EDITOR_COUNTS")
    def expanded_raw(value):
        require(type(value) is dict and set(value) == {"value", "read"}, "EDITOR_RAW_ENVELOPE")
        r = value["read"]
        require(r.get("complete") is True and r.get("truncated") is False and r.get("errorCount") == 0 and r.get("errors") == [], "EDITOR_RAW_INCOMPLETE")
        require(type(r.get("visitedValues")) is int and 0 <= r["visitedValues"] <= 65536 and type(r.get("payloadBytes")) is int and 0 <= r["payloadBytes"] <= 8 * 1024 * 1024, "EDITOR_RAW_BUDGET")
        return canonical_tree(value["value"])
    aggregate = None; root_keys = set(); used_roots = set()
    if shared:
        aggregate = expanded_raw(content["rawFields"])
        tree = content["rawFields"]["value"]
        require(set(tree) == {"root", "objects"} and set(tree["root"]) == {"refId"}, "EDITOR_SHARED_ROOT")
        matches = [o for o in tree["objects"] if o.get("objectId") == tree["root"]["refId"]]
        require(len(matches) == 1 and matches[0].get("type", "").startswith("System.Collections.Generic.Dictionary`2"), "EDITOR_SHARED_DICTIONARY")
        entries = matches[0]["entries"]
        require(matches[0]["count"] == len(entries) and all(set(e) == {"key", "value"} and type(e["key"]) is str for e in entries), "EDITOR_SHARED_ENTRIES")
        root_keys = {e["key"] for e in entries}
        require(len(root_keys) == len(entries), "EDITOR_SHARED_DUPLICATE_KEY")
    def raw(value, expected_key):
        if not shared: return expanded_raw(value)
        require(type(value) is dict and set(value) == {"rootKey"} and value["rootKey"] == expected_key and expected_key in root_keys and expected_key not in used_roots, "EDITOR_SHARED_ROOT_KEY:" + expected_key)
        used_roots.add(expected_key)
        return value
    entities, graphs, pairs = {}, {}, []
    for identity, e in unique(content["entities"], "id", "EDITOR_ENTITY").items():
        require(type(e["templateId"]) is int and e["templateId"] > 0, "EDITOR_TEMPLATE")
        bindings = [b["id"] for b in e["graphBindings"]]
        require(len(bindings) == len(set(bindings)), "EDITOR_DUPLICATE_BINDING")
        pairs.extend((identity, x) for x in bindings)
        # All captured entity columns are preserved. Transform remains a raw
        # cache comparison; these obfuscated vector roles are not assumed.
        value = dict(e, rawFields=raw(e["rawFields"], "entity:" + str(identity)), graphBindings=sorted(e["graphBindings"], key=lambda x: x["id"]))
        entities[identity] = value
    node_count = link_count = 0
    for identity, g in unique(content["graphs"], "id", "EDITOR_GRAPH").items():
        nodes = unique(g["nodes"], "id", "EDITOR_NODE")
        require(g["nodeCount"] == len(nodes) <= 4096 and g["linkCount"] == len(g["links"]) <= 16384, "EDITOR_GRAPH_COUNTS")
        ns = {}
        for nid, n in nodes.items():
            require(type(n["definition"]["id"]) is int and n["definition"]["id"] > 0, "EDITOR_NODE_DEFINITION")
            ns[nid] = dict(n, rawFields=raw(n["rawFields"], "node:" + str(identity) + ":" + str(nid)), layout={k:raw(v, "layout-" + k + ":" + str(identity) + ":" + str(nid)) for k,v in n["layout"].items()})
        edges = [normalized_edge(e["from"], e["to"]) for e in g["links"]]
        require(len(edges) == len(set(edges)) and all(e[0] in nodes and e[3] in nodes for e in edges), "EDITOR_EDGE_SET")
        require(sorted(g["boundEntityIds"]) == sorted(e for e, gid in pairs if gid == identity), "EDITOR_BINDING_BACKREF")
        graphs[identity] = dict(g, nodes=ns, links=sorted(edges), rawFields=raw(g["rawFields"], "graph:" + str(identity)), boundEntityIds=sorted(g["boundEntityIds"]))
        node_count += len(ns); link_count += len(edges)
    require(content["nodeCount"] == node_count and content["linkCount"] == link_count and all(g in graphs for _,g in pairs), "EDITOR_TOTALS_OR_BINDING")
    retained = raw(content["retainedInitialization"], "retained-init")
    require(not shared or root_keys == used_roots, "EDITOR_SHARED_UNCONSUMED_ROOT")
    result = dict(entities=entities, graphs=graphs, bindings=sorted(pairs), retainedInitialization=retained)
    if shared: result["rawFields"] = aggregate
    return result



def native_entity_identity(context, formal):
    rows = unique(context["entities"], "id", "NATIVE_ENTITY")
    require(set(rows) == set(formal["entities"]), "NATIVE_FORMAL_ENTITY_SET")
    require(all(type(v["configId"]) is int and v["configId"] > 0 and v["dictionaryKey"] == k for k,v in rows.items()), "NATIVE_CONFIG_ID_OR_DICTIONARY_KEY")
    require(context["levelCatalog"]["counts"]["dirtyByte"] == 0, "NATIVE_UNSAVED_CHANGES")
    result = {k:v["configId"] for k,v in rows.items()}
    require(result == {k:v["configurationReferenceId"] for k,v in formal["entities"].items()}, "NATIVE_FORMAL_CONFIGURATION_REFERENCE")
    return result

def compare_content(before, after, formal, native_before, native_after):
    require(before == after, "EDITOR_ROUNDTRIP_CONTENT_CHANGED")
    require(set(before["entities"]) == set(formal["entities"]), "FORMAL_ENTITY_SET")
    expected = {k: v["configurationReferenceId"] for k,v in formal["entities"].items()}
    require({k:v["templateId"] for k,v in before["entities"].items()} == expected, "FORMAL_CONFIGURATION_REFERENCES")
    require(native_entity_identity(native_before, formal) == native_entity_identity(native_after, formal), "NATIVE_CONFIG_REFERENCE_CHANGED")
    require(set(before["graphs"]) == set(formal["graphs"]), "FORMAL_GRAPH_SET")
    for gid, g in before["graphs"].items():
        require({nid:n["definition"]["id"] for nid,n in g["nodes"].items()} == formal["graphs"][gid]["nodes"], "FORMAL_NODES:" + str(gid))
        require(g["links"] == formal["graphs"][gid]["edges"], "FORMAL_EDGES:" + str(gid))
    require(before["bindings"] == formal["bindings"], "FORMAL_BINDINGS_MISMATCH")
    return dict(editorRoundtripPreserved=True, nativeEntitySetMatchesFormal=True,
                formalEntityGraphStructureMatches=True, bindingsMatch=True,
                formalConfigurationReferencesMatch=True, formalTemplateMappingVerified=False,
                formalParameterMappingVerified=False, formalGeometryMappingVerified=False)


def observer_evidence(before, after, started, finished):
    def inspect(doc):
        require(doc.get("ok") is True and doc.get("active") is True and doc.get("observerRegistered") is True and doc.get("originalReceiversPreserved") is True, "OBSERVER_INACTIVE")
        require(doc.get("callbackErrors") == 0 and doc.get("contractRejectedCallbacks") == 0 and doc.get("observerCleanupError") is None, "OBSERVER_CALLBACK_ERROR")
        x = doc["levelInitialization"]
        require(all(x.get(k) is True for k in ("started", "active", "managerSameReference", "originalReceiverOrderPreserved", "builtinBeforeOwnObserver")) and x.get("ownReceiverCount") == 1, "INIT_OBSERVER_CONTRACT")
        require(x.get("source") == "received-1022-packet-observer" and x.get("overflow") is False and all(x.get(k) == 0 for k in ("parseErrors", "evidenceErrors", "threadErrors", "droppedEvents")), "INIT_OBSERVER_ERRORS")
        require(x.get("currentPayloadPresent") is True and x.get("currentLevelId") == LEVEL and x.get("baselineLevelId") == LEVEL, "INIT_LEVEL")
        events = x["events"]
        require(x["retainedEvents"] == len(events) == x["sequence"] <= 16 and [e["sequence"] for e in events] == list(range(1, len(events)+1)), "INIT_EVENT_COMPLETENESS")
        return x
    b, a = inspect(before), inspect(after)
    require(b["observationId"] == a["observationId"] and b["initStartedUtc"] == a["initStartedUtc"] and utc(b["initStartedUtc"]) <= started, "INIT_OBSERVATION_ID")
    require(b["currentPayloadSameReference"] is True and a["currentPayloadSameReference"] is False, "INIT_CACHE_NOT_REPLACED")
    require(a["events"][:len(b["events"])] == b["events"], "INIT_HISTORY_CHANGED")
    fresh = a["events"][len(b["events"]):]
    require(len(fresh) == 1 and fresh[0].get("parsed") is True and fresh[0].get("error") is None and fresh[0]["levelId"] == LEVEL and started <= utc(fresh[0]["receivedUtc"]) <= finished, "INIT_NOT_SINGLE_FRESH_TARGET")
    return dict(freshInitializationBound=True, noObserverErrors=True, eventSequence=fresh[0]["sequence"], loadProof=False)


def ipc_evidence(before, after, game_pid, editor_pid):
    api = module("_reopen_ipc_evidence", ROOT / "tools/editor-bridge/connection-evidence.py")
    observations = [api.classify(x["endpoints"], editor_pid, game_pid) for x in (before, after)]
    require(all(x["reciprocalPairObserved"] and not x["editorSelfConnectionObserved"] for x in observations), "IPC_PAIR_MISSING")
    require(sorted(observations[0]["pairs"], key=lambda x: json.dumps(x, sort_keys=True)) == sorted(observations[1]["pairs"], key=lambda x: json.dumps(x, sort_keys=True)), "IPC_ENDPOINT_CHANGED")
    # Process creation times must be recorded beside both OS snapshots, rather
    # than inferring identity from recycled PIDs.
    require(sorted(before["processes"], key=lambda x: x["pid"]) == sorted(after["processes"], key=lambda x: x["pid"]), "IPC_PROCESS_IDENTITY_CHANGED")
    pids = {x["pid"] for x in before["processes"]}
    require(pids == {game_pid, editor_pid} and all(type(x["creationFileTime"]) is int and x["creationFileTime"] > 0 for x in before["processes"]), "IPC_PROCESS_SNAPSHOT")
    return dict(ipcIdentityPreserved=True, pairs=observations[0]["pairs"])


def native_run(entry, session, *, action=False):
    require(type(entry) is dict and set(entry) == {"path", "hashes"}, "RUN_REFERENCE")
    run = Path(entry["path"]).resolve()
    require(run.is_relative_to(ROOT / ".runtime"), "RUN_OUTSIDE_RUNTIME")
    required = {"prepared.json", "build-result.json", "stdout.jsonl", "exit.json"}
    require(required <= set(entry["hashes"]), "RUN_RAW_FILES_REQUIRED")
    for name, digest in entry["hashes"].items():
        require(Path(name).name == name and sha(run / name) == digest, "RUN_HASH:" + name)
    prepared, build, exit_record = (json_read(run / name) for name in ("prepared.json", "build-result.json", "exit.json"))
    require(prepared.get("launchable") is True and prepared.get("compileOnly") is False and prepared.get("allowWrites") is action and prepared.get("profileSha256") == profiles.PROFILE_SHA256, "RUN_PROFILE")
    for field in review_api.SESSION_FIELDS:
        require(prepared["session"].get(field) == session.get(field), "RUN_SESSION:" + field)
    artifacts = build["hashes"]
    require("prepared.json" in artifacts and "target_config.h" in artifacts and len(artifacts) >= 4, "BUILD_ARTIFACT_PIN_SET")
    for name, digest in artifacts.items():
        require(Path(name).name == name and sha(run / name) == digest, "BUILD_ARTIFACT_CHANGED:" + name)
    expected_sources = set(readonly.SOURCES)
    if action:
        expected_sources.update({"reopen_action.cpp", "reopen_action.h", "reopen_action_validation.cpp", "reopen_call.cpp", "reopen_call.h", "hook_reopen_probe.cpp", "hook_reopen_receipt.cpp", "hook_reopen_protocol.h", "reopen_route.generated.h"})
    require(expected_sources <= set(prepared["sources"]), "NATIVE_SOURCE_PIN_SET")
    for name, digest in prepared["sources"].items():
        require(Path(name).name == name and sha(Path(__file__).with_name("native") / name) == digest, "NATIVE_SOURCE_CHANGED:" + name)
    require(exit_record.get("executed") is True and exit_record.get("exitCode") == 0 and exit_record.get("error") is None, "NATIVE_EXECUTION_FAILED")
    require(utc(exit_record["startedUtc"]) <= utc(exit_record["finishedUtc"]), "NATIVE_TIMES")
    decoder = readonly.load_decoder()
    record, _ = decoder.read_probe(run / "stdout.jsonl")
    context = decoder.decode_snapshot(record)
    validated = readonly.validate_receipt(record, context, prepared, profiles.load_profile())
    reasons = validated["reasons"]
    if action:
        # Dedicated action intentionally reports business ok=false and uses a
        # different scope. Its own ABI/provenance is checked below, not patched.
        reasons = [r for r in reasons if r not in ("RECEIPT_SCOPE", "HELPER_TOKEN", "BUSINESS_SUCCESS")]
    require(not reasons and validated["baselineNonempty"] and context["levelObservation"]["levelId"] == LEVEL, "NATIVE_CONTEXT:" + ",".join(reasons))
    for key, api in (("levelCatalog", catalog_api), ("lifecycleType", type_api), ("schedulerCoroutines", scheduler_api)):
        require(prepared.get(key + "ProfileSha256") == api.PROFILE_SHA256, "NATIVE_EXTENSION_PROFILE:" + key)
        context[key] = api.decode(record, context, api.load_profile())
        require(context[key]["ok"], "NATIVE_EXTENSION_FAILED:" + key)
    require(prepared.get("schedulerCoroutinesDecoderSha256") == sha(Path(scheduler_api.__file__)), "SCHEDULER_DECODER_PIN")
    if action:
        require(prepared.get("reopenGuardsProfileSha256") == guards_api.PROFILE_SHA256 and prepared.get("reopenGuardsDecoderSha256") == sha(Path(guards_api.__file__)), "GUARD_DECODER_PIN")
        context["reopenGuards"] = guards_api.decode(record, context, guards_api.load_profile(), prepared)
        require(context["reopenGuards"]["ok"] and context["reopenGuards"]["bothFalseProven"], "ACTION_GUARDS")
        decoded_action = decode_action(record, prepared, context)
        derived = dict(record)
        for suffix in ("Hex", "Bytes", "Status"):
            derived["schedulerCoroutines" + suffix] = record["postSchedulerCoroutines" + suffix]
        post = scheduler_api.decode(derived, context, scheduler_api.load_profile())
        progress = decode_observation(record, context, decoded_action["invocation"], post)
    else:
        decoded_action = progress = post = None
    return dict(path=run, prepared=prepared, record=record, context=context, exit=exit_record,
                action=decoded_action, loadProgress=progress, postScheduler=post)


def validate(index):
    """Fail closed; return partial findings without creating a release artifact."""
    result = dict(schemaVersion=1, scope="fixed-1839-reopen-roundtrip", requestId=index.get("requestId"),
        levelId=LEVEL, businessVerified=False, reopenRoundtripVerified=False,
        formalParameterMappingVerified=False, formalGeometryMappingVerified=False,
        internalCoroutineCompletionVerified=False, safeToRelease=False,
        checks={}, reasons=[], limits=[
            "Full before/after captured editor business fields are compared; UI/subscriber base fields are excluded by the capture contract.",
            "Formal GIL parameters are parsed and retained, but their independent tag mapping to editor fields is not established.",
            "Configuration references are matched to GIL entity field 2/1; the parser field-8 template value is a separate field, not a claimed runtime template mapping.",
            "Native readback covers entity IDs/dictionary keys and before/after opaque config reference IDs; config IDs can be shared and are not assumed to be template or instance IDs.",
            "Error audit covers action/capture/observer errors, not the absence of every possible game log error.",
            "Only fixed reconciliation can release the original pending lease; no result authorizes replay."])
    try:
        require(index.get("schemaVersion") == 1 and re.fullmatch("[0-9a-f]{32}", str(index.get("requestId"))) is not None, "INDEX_SCHEMA")
        names = {"lease", "claim", "dispatch", "session", "review", "beforeEditor", "afterEditor", "beforeObserver", "afterObserver", "beforeIpc", "afterIpc", "beforeAccount", "afterAccount", "formalGil"}
        require(set(index["files"]) == names and set(index["runs"]) == {"before", "action", "after"}, "INDEX_INPUT_SET")
        paths = {k:checked_path(v, runtime=k != "formalGil") for k,v in index["files"].items()}
        docs = {k:json_read(p) for k,p in paths.items() if k != "formalGil"}
        lease, dispatch, session = docs["lease"], docs["dispatch"], docs["session"]
        require(paths["lease"].read_bytes() == paths["claim"].read_bytes(), "LEASE_CLAIM_MISMATCH")
        require(lease.get("schema") == 1 and lease.get("action") == "reopen-current" and lease.get("requestId") == index["requestId"] and lease.get("levelId") == LEVEL, "LEASE_IDENTITY")
        require(lease["sessionSha256"] == sha(paths["session"]) and lease["reviewSha256"] == sha(paths["review"]) and lease["accountBaselineSha256"] == sha(paths["beforeAccount"]) and lease["acceptanceVerifierSha256"] == sha(Path(__file__)), "LEASE_SOURCE_BINDINGS")
        require(Path(lease["sessionPath"]).resolve() == paths["session"], "LEASE_SESSION_PATH")
        require(dispatch.get("schema") == 1 and dispatch.get("requestId") == index["requestId"] and dispatch.get("leaseSha256") == sha(paths["lease"]) and dispatch.get("status") == "dispatch-returned-business-pending" and dispatch.get("retryAttempted") is False, "DISPATCH_BINDING")
        before = native_run(index["runs"]["before"], session)
        action = native_run(index["runs"]["action"], session, action=True)
        after = native_run(index["runs"]["after"], session)
        require(action["loadProgress"]["loadOccurred"] is True, "ACTION_LOAD_NOT_PROVEN")
        p = action["prepared"]
        require(p.get("requestId") == index["requestId"] and p.get("reviewSha256") == lease["reviewSha256"] and Path(p["reviewPath"]).resolve() == paths["review"], "ACTION_REQUEST_REVIEW")
        require(dispatch["nativeReceiptSha256"] == sha(action["path"] / "stdout.jsonl") and dispatch.get("hookCleanupVerified") is True, "DISPATCH_RAW_RECEIPT")
        reviewed = docs["review"]
        require(reviewed.get("schemaVersion") == 1 and reviewed.get("operation") == "level.reopen-current" and reviewed.get("allowedCalls") == 1 and reviewed.get("levelId") == LEVEL and reviewed.get("requestId") == index["requestId"], "REVIEW_CONTRACT")
        for field in review_api.SESSION_FIELDS:
            require(reviewed["session"].get(field) == session.get(field), "REVIEW_SESSION:" + field)
        require(reviewed["bridgeRunId"] == lease["bridgeRunId"] and reviewed["accountBaselineSha256"] == sha(paths["beforeAccount"]) and Path(reviewed["accountBackupManifest"]).resolve() == paths["beforeAccount"], "REVIEW_ACCOUNT_BRIDGE")
        require(Path(reviewed["baselineRun"]).resolve() == before["path"] and reviewed["baselineHashes"] == {n:sha(before["path"] / n) for n in ("prepared.json", "build-result.json", "stdout.jsonl", "exit.json")}, "REVIEW_BASELINE")
        for review_key, evidence_key in (("editorBaseline", "beforeEditor"), ("observerBaseline", "beforeObserver")):
            require(Path(reviewed[review_key]["path"]).resolve() == paths[evidence_key] and reviewed[review_key]["sha256"] == sha(paths[evidence_key]), "REVIEW_EDITOR_OBSERVER_BASELINE")
        started, returned = utc(action["exit"]["startedUtc"]), utc(action["exit"]["finishedUtc"])
        require(utc(reviewed["createdUtc"]) <= started < utc(reviewed["expiresUtc"]) and 0 < (utc(reviewed["expiresUtc"]) - utc(reviewed["createdUtc"])).total_seconds() <= 300, "REVIEW_TIME_AT_DISPATCH")
        finished = utc(after["exit"]["finishedUtc"])
        require(utc(before["exit"]["finishedUtc"]) <= started <= returned <= utc(after["exit"]["startedUtc"]), "NATIVE_EVIDENCE_ORDER")
        for key in ("beforeEditor", "beforeIpc"):
            require(utc(docs[key]["observedUtc"]) <= started, "BEFORE_EVIDENCE_ORDER:" + key)
        for key in ("afterEditor", "afterIpc"):
            require(utc(docs[key]["observedUtc"]) >= returned, "AFTER_EVIDENCE_ORDER:" + key)
        finished = max(finished, utc(docs["afterEditor"]["finishedUtc"]), utc(docs["afterIpc"]["observedUtc"]))
        result["checks"].update(dispatchExactlyOnce=True, hookCleanupVerified=True,
            loadOccurredAfterDispatch=True, loadProgress=action["loadProgress"])
        account_before, account_after = read_account(paths["beforeAccount"]), read_account(paths["afterAccount"])
        require(account_before["rows"] == account_after["rows"], "ACCOUNT_FILES_OR_METADATA_CHANGED")
        require(Path(account_before["manifest"]["source"]).resolve() == Path(account_after["manifest"]["source"]).resolve() and paths["formalGil"] == (Path(account_before["manifest"]["source"]) / FORMAL_RELATIVE).resolve(), "FORMAL_ACCOUNT_PATH")
        require(sha(paths["formalGil"]) == sha(account_before["formal"]) == sha(account_after["formal"]), "FORMAL_FILE_CHANGED")
        require(utc(account_before["manifest"]["createdUtc"]) <= started and utc(account_after["manifest"]["createdUtc"]) >= returned, "ACCOUNT_EVIDENCE_ORDER")
        formal = formal_content(paths["formalGil"])
        require(docs["beforeEditor"].get("schemaVersion") == docs["afterEditor"].get("schemaVersion") == 2, "CURRENT_SHARED_EDITOR_SCHEMA_REQUIRED")
        editor_before, editor_after = editor_content(docs["beforeEditor"]), editor_content(docs["afterEditor"])
        comparison = compare_content(editor_before, editor_after, formal, before["context"], after["context"])
        # The exact context captured immediately before the call must also match.
        compare_content(editor_before, editor_after, formal, action["context"], after["context"])
        result["checks"].update(comparison, protectedFilesAndMetadataUnchanged=True)
        result["checks"].update(observer_evidence(docs["beforeObserver"], docs["afterObserver"], started, finished))
        result["checks"].update(ipc_evidence(docs["beforeIpc"], docs["afterIpc"], session["pid"], index["editorPid"]))
        game_row = next(x for x in docs["beforeIpc"]["processes"] if x["pid"] == session["pid"])
        require(game_row["creationFileTime"] == session["processCreation"], "IPC_GAME_SESSION_CREATION")
        for key, entry in index["files"].items():
            checked_path(entry, runtime=key != "formalGil")
        for entry in index["runs"].values():
            for name, digest in entry["hashes"].items():
                require(sha(Path(entry["path"]) / name) == digest, "RUN_CHANGED_DURING_ACCEPTANCE")
        result.update(businessVerified=True, reopenRoundtripVerified=True,
            formalCounts=dict(entities=len(formal["entities"]), graphs=len(formal["graphs"]),
                nodes=sum(len(g["nodes"]) for g in formal["graphs"].values()), bindings=len(formal["bindings"])),
            verifierSourceSha256=sha(Path(__file__)))
    except (ValueError, KeyError, TypeError, OSError, OverflowError, struct.error) as exc:
        result["reasons"].append(str(exc))
    return result



ACCEPTANCE_CHECKS = ("dispatchExactlyOnce", "loadOccurredAfterDispatch", "freshInitializationBound",
    "nativeEntitySetMatchesFormal", "editorRoundtripPreserved", "formalEntityGraphStructureMatches",
    "bindingsMatch", "protectedFilesAndMetadataUnchanged", "ipcIdentityPreserved", "noObserverErrors", "hookCleanupVerified")
EXTRA_PROJECT_FILES = (
    "tools/game-executor/native_reopen_acceptance.py", "tools/game-executor/verify-created-save.py",
    "tools/editor-bridge/audit-native-enums.py", "tools/editor-bridge/build-newdemo-static.py",
    "tools/editor-bridge/build-static-level-draft.py", "tools/editor-bridge/connection-evidence.py",
    "tools/beyond-save/gil_container.py")
EXTRA_PACKAGES = ("google/protobuf", "google/_upb", "pydantic", "pydantic_core", "typing_inspection", "annotated_types")


def dependency_files():
    files = [ROOT / name for name in EXTRA_PROJECT_FILES]
    base = Path(sys.executable).resolve().parent / "Lib/site-packages"
    files.append(base / "typing_extensions.py")
    directories = [ROOT / "third_party/auto-miliastra/src/miliastra_agent"]
    directories += [base / name for name in EXTRA_PACKAGES]
    for folder in directories:
        require(folder.is_dir(), "VERIFIER_DEPENDENCY_DIRECTORY:" + str(folder))
        files.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix in (".py", ".pyd", ".dll") and "__pycache__" not in p.parts)
    require(all(p.is_file() for p in files), "VERIFIER_DEPENDENCY_MISSING")
    return sorted({p.resolve() for p in files}, key=lambda p:str(p).casefold())


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def work_path(work):
    p = Path(work).resolve()
    require(p.parent == (ROOT / ".runtime/editor-bridge/native-dispatch").resolve() and re.fullmatch("[0-9a-f]{32}", p.name) is not None, "REOPEN_FIXED_WORK_PATH")
    return p


def acceptance_candidate(work):
    work = work_path(work)
    index_path = work / "reopen-inputs.json"
    index = json_read(index_path)
    require(index["requestId"] == work.name, "REOPEN_WORK_REQUEST")
    # Immutable claim is used as the lease evidence; active ownership is checked
    # again by PowerShell. This also supports idempotent readback after archive.
    for field, name in (("lease", "reopen-claim.json"), ("claim", "reopen-claim.json"), ("dispatch", "reopen-dispatch.json")):
        require(Path(index["files"][field]["path"]).resolve() == work / name, "REOPEN_FIXED_INPUT:" + field)
    dependencies = {str(p):sha(p) for p in dependency_files()}
    result = validate(index)
    require(result["reopenRoundtripVerified"] is True and result["businessVerified"] is True, "REOPEN_BUSINESS_NOT_VERIFIED:" + ";".join(result["reasons"]))
    require(all(result["checks"].get(name) is True for name in ACCEPTANCE_CHECKS), "REOPEN_REQUIRED_CHECKS")
    lease_path = work / "reopen-claim.json"; dispatch_path = work / "reopen-dispatch.json"
    lease = json_read(lease_path); dispatch = json_read(dispatch_path)
    require(dependencies == {str(p):sha(p) for p in dependency_files()}, "VERIFIER_DEPENDENCY_CHANGED_DURING_READ")
    dependency_bytes = canonical_bytes({"schemaVersion":1,"files":dependencies})
    result_bytes = canonical_bytes(result)
    accepted = dict(schema=2, operation="level.reopen-current", scope="fixed-1839-reopen-roundtrip",
        requestId=work.name, levelId=LEVEL, leaseSha256=sha(lease_path), dispatchSha256=sha(dispatch_path),
        nativeReceiptSha256=dispatch["nativeReceiptSha256"], reviewSha256=lease["reviewSha256"],
        accountBaselineSha256=lease["accountBaselineSha256"], verifierSourceSha256=sha(Path(__file__)),
        inputsSha256=sha(index_path), dependenciesSha256=hashlib.sha256(dependency_bytes).hexdigest(),
        verificationResultSha256=hashlib.sha256(result_bytes).hexdigest(), businessVerified=True,
        reopenRoundtripVerified=True, formalParameterMappingVerified=False, formalGeometryMappingVerified=False,
        internalCoroutineCompletionVerified=False, checks={name:result["checks"][name] for name in ACCEPTANCE_CHECKS})
    return accepted, dependency_bytes, result_bytes


def exclusive_bytes(path, data):
    if path.exists():
        require(path.read_bytes() == data, "REOPEN_IMMUTABLE_ARTIFACT_CONFLICT:" + path.name)
        return
    with path.open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def produce(work):
    work = work_path(work)
    accepted, dependencies, result = acceptance_candidate(work)
    exclusive_bytes(work / "reopen-verifier-dependencies.json", dependencies)
    exclusive_bytes(work / "reopen-verification.json", result)
    exclusive_bytes(work / "reopen-acceptance.json", canonical_bytes(accepted))
    return dict(ok=True, schema=2, requestId=work.name, scope=accepted["scope"],
                acceptanceSha256=sha(work / "reopen-acceptance.json"), inputsSha256=accepted["inputsSha256"])


def verify_acceptance(work, expected_hash):
    work = work_path(work)
    require(re.fullmatch("[0-9a-f]{64}", expected_hash) is not None, "REOPEN_ACCEPTANCE_HASH_FORMAT")
    accepted_path = work / "reopen-acceptance.json"
    require(sha(accepted_path) == expected_hash, "REOPEN_ACCEPTANCE_HASH")
    # Recompute all business decisions from the raw files each time; an existing
    # acceptance file, boolean, or its hash is never itself authority to release.
    expected, dependencies, result = acceptance_candidate(work)
    require(accepted_path.read_bytes() == canonical_bytes(expected) and
        (work / "reopen-verifier-dependencies.json").read_bytes() == dependencies and
        (work / "reopen-verification.json").read_bytes() == result, "REOPEN_INDEPENDENT_RECOMPUTATION_MISMATCH")
    return dict(ok=True, schema=2, requestId=work.name, scope=expected["scope"],
                acceptanceSha256=expected_hash, inputsSha256=expected["inputsSha256"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evidence_index", type=Path, nargs="?")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--produce", type=Path)
    ap.add_argument("--verify-work", type=Path)
    ap.add_argument("--acceptance-sha256")
    args = ap.parse_args()
    try:
        require(sum(x is not None for x in (args.evidence_index, args.produce, args.verify_work)) == 1, "ONE_FIXED_MODE_REQUIRED")
        if args.produce:
            require(args.output is None and args.acceptance_sha256 is None, "PRODUCE_ARGUMENTS")
            result = produce(args.produce)
        elif args.verify_work:
            require(args.output is None and args.acceptance_sha256 is not None, "VERIFY_ARGUMENTS")
            result = verify_acceptance(args.verify_work, args.acceptance_sha256)
        else:
            require(args.acceptance_sha256 is None, "DIAGNOSTIC_ARGUMENTS")
            result = validate(json_read(args.evidence_index))
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            target = args.output.resolve()
            require(target.is_relative_to(ROOT / ".runtime") and target.name not in ("reopen-acceptance.json", "reopen-release.json"), "DIAGNOSTIC_OUTPUT_ONLY")
            with target.open("x", encoding="utf-8") as stream: stream.write(text + "\n")
        print(text)
        return 0 if result.get("ok") is True or result.get("reopenRoundtripVerified") is True else 2
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps(dict(ok=False,error=str(exc),businessVerified=False,safeToRelease=False)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
