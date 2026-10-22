"""Read-only checks of the bounded, unbound finish candidate; not an encoder."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Upstream shapes, with settle_stage corrected by native R44 node 77 readback
# in run 5dcd3324-dd37-425c-8bf3-b372b55077c3. This remains an unbound candidate.
PINS = {
    "when_entering_collision_trigger": ([], ["entity", "guid", "entity", "guid", "int"], 0, 1),
    "get_player_entity_to_which_the_character_belongs": (["entity"], ["entity"], 0, 0),
    "set_player_settlement_success_status": (["entity", "enum"], [], 1, 1),
    "settle_stage": (["bool"], [], 1, 1),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(ir, pending):
    require(ir["ir_version"] == 1 and ir["ir_type"] == "node_graph", "Unsupported IR")
    require(ir["graph"]["type"] == "server" and ir["graph"]["sub_type"] == "entity", "Wrong graph kind")
    require("id" not in ir["graph"] and "mode" not in ir["graph"], "Candidate must remain unbound")
    nodes = ir["nodes"]
    require(len(nodes) == 4, "Expected four audited nodes")
    by_id = {node["id"]: node for node in nodes}
    require(len(by_id) == len(nodes), "Duplicate node IDs")
    require(all(type(i) is int and i > 0 for i in by_id), "Invalid local node ID")
    require({n["type"] for n in nodes} == set(PINS), "Unexpected node types")
    flow = []
    for node in nodes:
        inputs, _, flow_in, flow_out = PINS[node["type"]]
        args = node.get("args", [])
        require(len(args) == len(inputs), "Wrong input count")
        for expected, arg in zip(inputs, args):
            if arg["type"] == "conn":
                ref = arg["value"]
                require(ref["node_id"] in by_id, "Dangling data reference")
                source_outputs = PINS[by_id[ref["node_id"]]["type"]][1]
                require(type(ref["index"]) is int and 0 <= ref["index"] < len(source_outputs), "Invalid data pin")
                require(source_outputs[ref["index"]] == ref["type"] == expected, "Data type mismatch")
            elif expected == "bool":
                require(arg["type"] == "bool" and arg["value"] is True, "Finish must request successful settlement explicitly")
            else:
                require(expected == arg["type"] == "enum" and arg["value"] == "settlement_status_victory", "Unexpected literal")
        for edge in node.get("next", []):
            require(edge["node_id"] in by_id, "Dangling flow reference")
            require(edge["source_index"] == 0 and flow_out == 1, "Invalid flow source")
            require(edge["target_index"] == 0 and PINS[by_id[edge["node_id"]]["type"]][2] == 1, "Invalid flow target")
            flow.append((node["type"], by_id[edge["node_id"]]["type"]))
    require(flow == [("when_entering_collision_trigger", "set_player_settlement_success_status"), ("set_player_settlement_success_status", "settle_stage")], "Wrong settlement flow")
    require(pending["deploymentAllowed"] is False and pending["conditionEvidence"] == "missing", "Unverified deployment state")
    require(all(pending[key] is None for key in ("graphId", "graphMode", "goalEntityGuid", "triggerId")), "Unexpected live binding")
    require(pending["runtimeTypeGuardImplemented"] is False and pending["triggerIdGuardImplemented"] is False, "Do not claim missing guards")
    return {"structure": "passed", "nodeCount": len(nodes), "encoded": False, "deploymentAllowed": False, "gameVerified": False, "scope": "bounded candidate structure only"}


if __name__ == "__main__":
    ir = json.loads((ROOT / "finish.unbound.ir.json").read_text(encoding="utf-8-sig"))
    pending = json.loads((ROOT / "bindings.pending.json").read_text(encoding="utf-8-sig"))
    print(json.dumps(check(ir, pending), ensure_ascii=False))
