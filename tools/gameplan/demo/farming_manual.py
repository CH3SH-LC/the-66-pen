"""Offline player graph for one Z control, manual farming and the existing shop.

The UI asset supplies the actual group indices.  This module neither creates a
keyboard binding nor connects to a game.  It retains all values in a complete
plan and emits a smaller node/edge batch followed by typed value writes.  The
79 timer sequence is deliberately written with the proven float element slot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct

from ..builder import GraphBuilder
from ..contracts import DATA_INPUT, default_store
from ..golden import freeze
from ..nodes import Graph, PRINT, SELF
from ..plan import GraphPlan
from ..modules import farm_interaction as farm, key_interaction as key, player_abilities as a, shop
from ..modules.distance_interaction import ENTITY, GUID

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NAME = "MW_API_FARM_MANUAL_PLAYER"
MAX_REQUEST_BYTES = 16 * 1024
DEFAULT_OUTPUT = ROOT / ".runtime/scratch/offline-farming-20261014/farm"


@dataclass(frozen=True)
class FarmManualConfig:
    group_index: int
    group_combo_index: int | None = None
    item_slot: str = "uint"
    variable_flag_slot: str = "enum"
    entity_guid_slot: str = "uint"
    plot_id: int = 1077936130
    shop_id: int = 1077936129
    seed_id: int = 1107296257
    crop_id: int = 1107296258
    farm_center: tuple[float, float, float] = (4.0, 0.0, 0.0)
    shop_center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 1.5
    shop_index: int = 1
    growth_seconds: float = 10.0

    def __post_init__(self):
        a.integer(self.group_index, "group_index", minimum=1)
        if self.group_combo_index is not None:
            a.integer(self.group_combo_index, "group_combo_index", minimum=1)
        a.config_id(self.shop_id, "shop_id")
        a.integer(self.shop_index, "shop_index", minimum=1)
        if self.plot_id == self.shop_id:
            raise ValueError("plot and shop must be distinct scene entities")
        if self.entity_guid_slot not in ("int", "uint"):
            raise ValueError("entity_guid_slot must explicitly be int or uint")
        for name in ("farm_center", "shop_center"):
            point = getattr(self, name)
            if (not isinstance(point, (tuple, list)) or len(point) != 3 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
                raise ValueError(f"{name} must contain three finite coordinates")
        if type(self.radius) not in (int, float) or not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("radius must be finite and positive")
        if math.dist(self.farm_center, self.shop_center) <= 2 * self.radius:
            raise ValueError("farm and shop interaction regions must not overlap")
        self.farm_config()

    def farm_config(self) -> farm.FarmConfig:
        return farm.FarmConfig(self.plot_id, self.seed_id, self.crop_id,
                              self.item_slot, self.variable_flag_slot, self.growth_seconds)


def build_plan(config: FarmManualConfig) -> GraphPlan:
    """Create one player-side 316 entry and one player-owned growth timer."""
    g = Graph(DEFAULT_NAME)
    owner = g.place(SELF, "owner")
    entry = key.on_control(g, group_index=config.group_index,
                           group_combo_index=config.group_combo_index)
    # 316 is delivered to the triggering player's graph. Also reject a foreign
    # event explicitly before any character lookup, item write or shop action.
    owned = a.route_refs(g, entry.gate, left=(owner, "self"), right=entry.player,
                         alias="interaction_owner", from_role="true")
    character = key.character_for_player(g, owned, player=entry.player)
    near_farm = key.near(g, character.gate, character=character.character,
                        center=config.farm_center, radius=config.radius, alias="near_farm")
    near_shop = key.near(g, near_farm, character=character.character,
                        center=config.shop_center, radius=config.radius, alias="near_shop",
                        from_role="false")
    plot = g.place(ENTITY, "plot")
    plot.const("guid", config.plot_id, config.entity_guid_slot)
    plot_guid = g.place(GUID, "plot_guid")
    plot_guid.data_from(plot, "entity", "entity")
    farm.install(g, near_farm, character=character.character,
                 plot=(plot, "entity"), plot_guid=(plot_guid, "guid"),
                 timer_owner=(owner, "self"), config=config.farm_config())
    shop_owner = g.place(ENTITY, "shop_owner")
    shop_owner.const("guid", config.shop_id, config.entity_guid_slot)
    shop.open_(g, near_shop, player=entry.player, shop_owner=(shop_owner, "entity"),
               shop_index=config.shop_index, alias="open_shop", from_role="true")
    away = g.place(PRINT, "too_far")
    near_shop.flow_to(away, "false")
    away.const("text", "INTERACT_MOVE_CLOSER", "string")
    g.validate()
    return g.plan


def _no_dispatch(_):
    raise RuntimeError("OFFLINE_PACKAGE_HAS_NO_RUNNER")


def request_line_bytes(payload: dict) -> int:
    """Conservative, non-secret sizing envelope for the fixed bridge line limit.

    Use maximum-width IDs and 128 nonce characters, plus whitespace from the
    ordinary Python JSON encoder. Future dispatch must re-check its actual line.
    """
    envelope = dict(payload, op="author-graph", id="f" * 32,
                    nonce="0" * 128, graphId=4294967295, name=DEFAULT_NAME,
                    expectedNodeCount=128)
    return len((json.dumps(envelope, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))


def package(config: FarmManualConfig, plan: GraphPlan | None = None) -> dict:
    """Return JSON-only complete plan, bounded batch, ordered values and manifest.

    ``followups[*].node`` is a zero-based batch index, not an engine node ID.
    Resolve it through the actual build receipt; never assume index + 1.
    All links are applied before values so generic input types are materialized.
    Bind only after every followup and independent graph verification succeeds.
    """
    expected = build_plan(config)
    plan = expected if plan is None else plan
    plan.validate()
    if freeze(plan) != freeze(expected):
        raise ValueError("MANUAL_PLAN_CONFIG_MISMATCH")
    batch = GraphBuilder(plan, _no_dispatch, run_id="offline-only").batch_plan_json()
    values = batch.pop("values")
    batch["values"] = []
    store = default_store()
    followups = []
    for source, value in zip(plan.consts, values):
        port = store.require(plan.aliases()[source.alias].definition_id).port(DATA_INPUT, source.port_index)
        value = dict(value, action="set-value", nodeAlias=source.alias, portKind=3,
                     expect={"serverParamType": port.server_param_type,
                             "genericId": port.generic_id})
        if source.alias == "farm_growth_timer" and source.port_index == 3:
            value["slot"] = "float"
        followups.append(value)
    batch_bytes = request_line_bytes({"action": "build-plan", "plan": batch})
    if batch_bytes >= MAX_REQUEST_BYTES:
        raise ValueError(f"MANUAL_GRAPH_BATCH_EXCEEDS_BRIDGE_LIMIT:{batch_bytes}")
    max_value_bytes = max(request_line_bytes(v) for v in followups)
    if max_value_bytes >= MAX_REQUEST_BYTES:
        raise ValueError("MANUAL_GRAPH_VALUE_EXCEEDS_BRIDGE_LIMIT")
    frozen = freeze(plan)
    digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=True, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    return {"plan": frozen, "batchPlan": batch, "followups": followups,
            "manifest": {"kind": "offline-manual-farming-player-v1", "candidateOnly": True,
                "runtimeVerified": False, "dispatchable": False, "config": asdict(config),
                "graphName": plan.name, "graphKind": plan.graph_kind, "bindingTarget": "player",
                "shape": {"nodes": len(plan.nodes), "edges": len(plan.edges), "values": len(plan.consts)},
                "planSha256": digest, "batchRequestBytesUpperBound": batch_bytes,
                "maxFollowupRequestBytesUpperBound": max_value_bytes,
                "requestLimitBytes": MAX_REQUEST_BYTES, "followupNodeReference": "zero-based batch index",
                "requiredBeforeBinding": ["actual UI indices match the configured single Z control",
                    "all batch links and typed followups verified from actual graph export",
                    "legacy automatic shop-opening and farming entry disabled by exact reviewed patches"],
                "runtimeAcceptance": ["Z opens existing shop only while nearby",
                    "Z consumes one seed then starts a 10-second player-owned timer",
                    "maturity leaves crop on plot until a fresh nearby Z press",
                    "native count reads after 686 reflect the just-finished mutation",
                    "full bag leaves plot ripe; retry after freeing space awards exactly one crop"],
                "limits": ["single player and one real plot; no persistence across player graph destruction",
                    "unexpected inventory delta locks plot for inspection instead of replay",
                    "timer delivery and UI Z dispatch still require game acceptance"]}}


def write_package(config: FarmManualConfig, output: Path | str = DEFAULT_OUTPUT) -> dict:
    """Write candidate files only inside this project, independent of cwd."""
    output = Path(output)
    if not output.is_absolute():
        output = ROOT / output
    output = output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        raise ValueError("MANUAL_PACKAGE_OUTPUT_MUST_BE_PROJECT_RUNTIME")
    artifact = package(config)
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, value in artifact.items():
        target = output / (name + ".json")
        if not target.resolve().is_relative_to(ROOT / ".runtime"):
            raise ValueError("MANUAL_PACKAGE_OUTPUT_ESCAPES_PROJECT_RUNTIME")
        target.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        paths[name] = str(target)
    return paths


def _require(condition, code):
    if not condition:
        raise ValueError(code)


@lru_cache(maxsize=1)
def _export_loader():
    path = ROOT / "tools/editor-bridge/audit-native-enums.py"
    spec = importlib.util.spec_from_file_location("manual_farm_binary_graph_loader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _messages(fields, number):
    return [row.get("m", []) for row in fields if row["f"] == number]


def _message(fields, number):
    rows = _messages(fields, number)
    _require(len(rows) <= 1, f"NATIVE_SCHEMA_DUPLICATE_MESSAGE:{number}")
    return rows[0] if rows else []


def _scalar(fields, number, default=0):
    return next((row["v"] for row in fields if row["f"] == number and "v" in row), default)


@lru_cache(maxsize=1)
def _resource_paths():
    rows = [row for path in (ROOT / "data/node-contracts/variants/server").glob("bucket-*.json")
            for row in json.loads(path.read_text(encoding="utf-8"))]
    return {row["stableKey"]["definitionId"]: ROOT / ".runtime/editor-catalog/decoded" /
            ("Beyond__Node__" + Path(row["resource"]["path"]).name + ".json") for row in rows}


def _type_contract(plan):
    """Resolve this graph's concrete types, then official choices and kernels.

    Type equalities come from the declared wires and homogeneous arithmetic /
    comparisons. Kernel rules and generic option order come from cached decoded
    native resources, never from observed numeric node IDs or test expectations.
    """
    store = default_store()
    parents, facts = {}, {}
    def find(key):
        parents.setdefault(key, key)
        if parents[key] != key:
            parents[key] = find(parents[key])
        return parents[key]
    def union(left, right):
        parents[find(right)] = find(left)
    for node in plan.nodes:
        for port in store.require(node.definition_id).ports:
            if port.kind not in (3, 4):
                continue
            address = (node.alias, port.kind, port.index)
            find(address)
            if port.server_param_type:
                facts[address] = port.server_param_type
        if node.definition_id in (14, 200, 231, 233):
            union((node.alias, 3, 0), (node.alias, 3, 1))
            if node.definition_id == 200:
                union((node.alias, 3, 0), (node.alias, 4, 0))
    for edge in plan.edges:
        if edge.src_kind == 4:
            union((edge.src, 4, edge.src_index), (edge.dst, 3, edge.dst_index))
    for const in plan.consts:
        address = (const.alias, 3, const.port_index)
        if address not in facts and const.slot in ("int", "bool", "float", "string"):
            facts[address] = {"int": 3, "bool": 4, "float": 5, "string": 6}[const.slot]
    groups = {}
    for address, kind in facts.items():
        groups.setdefault(find(address), set()).add(kind)
    _require(all(len(values) == 1 for values in groups.values()), "PLAN_CONCRETE_TYPE_CONFLICT")
    types = {}
    for address in parents:
        values = groups.get(find(address), set())
        _require(len(values) == 1, "PLAN_GENERIC_TYPE_UNRESOLVED:" + repr(address))
        types[address] = next(iter(values))
    choices, kernels, defaults, source_hashes = {}, {}, {}, {}
    for node in plan.nodes:
        path = _resource_paths()[node.definition_id]
        raw = path.read_bytes()
        source_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        fields = json.loads(raw)["fields"]
        for pin in _messages(fields, 102) + _messages(fields, 103):
            signature = _message(pin, 3)
            address = (node.alias, _scalar(signature, 1), _scalar(signature, 2))
            definition = _message(pin, 4)
            if _scalar(definition, 1) == 10000:
                options = _messages(_message(definition, 103), 1)
                matching = [i for i, option in enumerate(options) if _scalar(option, 4) == types[address]]
                _require(len(matching) == 1, "NATIVE_GENERIC_OPTION_NOT_UNIQUE:" + repr(address))
                choices[address] = matching[0]
            # These are official fixed operation defaults, not invented values.
            if address[1:] == (3, 2) and node.definition_id in (231, 233):
                default = _message(definition, 2)
                defaults[address] = {"uint": _scalar(_message(default, 106), 1)}
        category = _message(fields, 4)
        identity = _message(category, 1)
        _require([_scalar(identity, n) for n in (1, 2, 3, 5)] ==
                 [10001, 20000, 22000, node.definition_id], "NATIVE_RESOURCE_IDENTITY")
        rules = _messages(category, 3)
        if not rules:
            kernels[node.alias] = node.definition_id
            continue
        matching = []
        for rule in rules:
            conditions = _messages(rule, 2)
            if conditions and all(choices.get((node.alias, _scalar(_message(c, 1), 1),
                    _scalar(_message(c, 1), 2))) == _scalar(c, 2) for c in conditions):
                matching.append(_scalar(_message(rule, 1), 5))
        _require(len(matching) == 1, "NATIVE_KERNEL_RULE_NOT_UNIQUE:" + node.alias)
        kernels[node.alias] = matching[0]
    return types, choices, kernels, defaults, source_hashes


def _leaf(value):
    for _ in range(4):
        if value.WhichOneof("storage") != "val_poly":
            return value
        _require(value.val_poly.HasField("actual_value"), "EMPTY_GENERIC_VALUE")
        value = value.val_poly.actual_value
    raise ValueError("GENERIC_VALUE_DEPTH")


def _verify_value(value, expected, slot, wanted_type, where):
    value = _leaf(value)
    _require(value.type_def.backend == 1 and value.type_def.server_side.type_tag == wanted_type,
             "VALUE_TYPE:" + where)
    tag, wanted = next(iter(expected.items()))
    _require(value.is_value_set == 1, "VALUE_NOT_SET:" + where)
    if tag == "list":
        _require(value.widget == 10002 and value.WhichOneof("storage") == "val_list" and
                 len(value.val_list.elements) == len(wanted), "TIMER_SEQUENCE_SHAPE:" + where)
        for child, expected_child in zip(value.val_list.elements, wanted):
            _verify_value(child, expected_child, "float", 5, where + ":element")
        return
    kind = "enum" if slot in ("enum", "bool") else tag
    branch, widget, field = {"uint": ("val_id", 1, "id"), "int": ("val_int", 2, "int"),
        "float": ("val_float", 4, "float"), "string": ("val_string", 5, "str"),
        "enum": ("val_enum", 6, "enum")}[kind]
    _require(value.widget == widget and value.WhichOneof("storage") == branch, "VALUE_STORAGE:" + where)
    actual = getattr(getattr(value, branch), field)
    equal = struct.pack("<f", actual) == struct.pack("<f", wanted) if tag == "float" else actual == wanted
    _require(equal, "VALUE_MISMATCH:" + where)


def verify_export(path: Path | str, config: FarmManualConfig, *, build_receipt: dict | Path | str) -> dict:
    """Validate a binary GIA/GIL using a successful build's actual alias mapping.

    The receipt must contain ``ok:true, graphId, nodeIds:{alias:nativeId}``, as
    GraphBuilder's per-node evidence does. A batch executor must first correlate
    its actual receipt to aliases, retaining that evidence; this verifier never
    invents IDs from offsets. The source container must be binary, not plan JSON.
    Full graph content is checked; binding, persistence and playtest are separate.
    """
    plan = build_plan(config)
    artifact = package(config, plan)
    return verify_plan_export(path, plan, artifact, build_receipt=build_receipt)


def verify_plan_export(path, plan, artifact, *, build_receipt):
    """Check a complete planned graph against native bytes and actual node IDs."""
    plan.validate()
    if not isinstance(build_receipt, dict):
        build_receipt = json.loads(Path(build_receipt).read_text(encoding="utf-8"))
    _require(build_receipt.get("ok") is True, "SUCCESSFUL_BUILD_RECEIPT_REQUIRED")
    graph_id, mapping = build_receipt.get("graphId"), build_receipt.get("nodeIds")
    a.config_id(graph_id, "receipt graphId")
    _require(isinstance(mapping, dict) and set(mapping) == set(plan.aliases()), "EXACT_ALIAS_MAPPING_REQUIRED")
    _require(all(type(n) is int and 0 < n <= 0xffffffff for n in mapping.values()) and
             len(set(mapping.values())) == len(mapping), "NATIVE_NODE_IDS_NOT_UNIQUE")
    path = Path(path).resolve()
    raw, graphs = _export_loader().load_graphs(path)
    matches = [g for g in graphs if g.identity.runtime_id == graph_id]
    _require(len(matches) == 1, "ACTUAL_GRAPH_NOT_UNIQUE")
    graph = matches[0]
    _require(graph.display_name == plan.name, "ACTUAL_GRAPH_NAME")
    _require((graph.identity.source_domain, graph.identity.service_domain, graph.identity.kind) ==
             (10000, 20000, 21001), "ACTUAL_GRAPH_DOMAIN")
    _require(not graph.port_mappings and not graph.blackboard and graph.entry_slot_index == 0 and
             graph.evaluation_interval == 0, "UNPLANNED_GRAPH_CONFIGURATION")
    nodes = {n.index: n for n in graph.nodes}
    _require(len(nodes) == len(graph.nodes) == len(plan.nodes) and set(nodes) == set(mapping.values()),
             "ACTUAL_NODES_NOT_EXACT")
    types, choices, kernels, defaults, hashes = _type_contract(plan)
    constants = {(c.alias, 3, c.port_index): row for c, row in zip(plan.consts, artifact["followups"])}
    observed, actual_pins = [], {}
    store = default_store()
    for planned in plan.nodes:
        alias, node = planned.alias, nodes[mapping[planned.alias]]
        _require(node.shell_ref.runtime_id == planned.definition_id, "ACTUAL_DEFINITION:" + alias)
        _require(node.kernel_ref.runtime_id == kernels[alias], "ACTUAL_KERNEL:" + alias)
        for identity in (node.shell_ref, node.kernel_ref):
            _require((identity.source_domain, identity.service_domain, identity.kind) ==
                     (10001, 20000, 22000), "ACTUAL_NODE_DOMAIN:" + alias)
        declared = {(p.kind, p.index): p for p in store.require(planned.definition_id).ports}
        for pin in node.pins:
            address = (alias, int(pin.shell_sig.kind), pin.shell_sig.index)
            key = address[1:]
            _require(address not in actual_pins and key in declared, "ACTUAL_PIN_NOT_UNIQUE_OR_DECLARED:" + repr(address))
            actual_pins[address] = pin
            _require((int(pin.kernel_sig.kind), pin.kernel_sig.index) == key, "ACTUAL_KERNEL_PIN:" + repr(address))
            if key[0] in (3, 4):
                _require(pin.type == types[address], "ACTUAL_PIN_TYPE:" + repr(address))
                if address in choices:
                    _require(pin.value.WhichOneof("storage") == "val_poly" and
                             pin.value.val_poly.chosen_type_index == choices[address],
                             "ACTUAL_GENERIC_CHOICE:" + repr(address))
                    value = _leaf(pin.value)
                    _require(value.type_def.backend == 1 and value.type_def.server_side.type_tag == types[address],
                             "ACTUAL_GENERIC_VALUE_TYPE:" + repr(address))
                if key[0] == 3 and address not in constants:
                    value = _leaf(pin.value)
                    if value.is_value_set:
                        _require(not pin.connections and address in defaults, "UNPLANNED_CONSTANT:" + repr(address))
                        _verify_value(value, defaults[address], "enum", types[address], repr(address))
            for link in pin.connections:
                _require((int(link.target_pin_kernel.kind), link.target_pin_kernel.index) ==
                         (int(link.target_pin_shell.kind), link.target_pin_shell.index), "TARGET_KERNEL_PIN")
                left = (node.index, key[0], key[1])
                right = (link.target_node_index, int(link.target_pin_shell.kind), link.target_pin_shell.index)
                if key[0] == 3:
                    left, right = right, left
                observed.append(left + right)
    expected_edges = Counter((mapping[e.src], e.src_kind, e.src_index,
                             mapping[e.dst], e.dst_kind, e.dst_index) for e in plan.edges)
    _require(Counter(observed) == expected_edges, "ACTUAL_EDGES_NOT_EXACT")
    required = set(constants) | set(choices)
    required.update((e.dst, 3, e.dst_index) for e in plan.edges if e.dst_kind == 3)
    _require(required <= set(actual_pins), "ACTUAL_REQUIRED_PINS_MISSING")
    for address, entry in constants.items():
        pin = actual_pins[address]
        _require(not pin.connections, "CONSTANT_HAS_SOURCE:" + repr(address))
        _verify_value(pin.value, entry["value"], entry["slot"], types[address], repr(address))
    _require(path.read_bytes() == raw, "EXPORT_CHANGED_DURING_VERIFICATION")
    return {"ok": True, "serializedContentVerified": True, "bindingVerified": False,
            "saveVerified": False, "playtestVerified": False, "inputPath": str(path),
            "inputSha256": hashlib.sha256(raw).hexdigest(), "graphId": graph_id,
            "graphName": graph.display_name, "shape": artifact["manifest"]["shape"],
            "mappingBasis": "successful build receipt alias-to-native-node-ID mapping",
            "actualNodeIds": mapping, "genericChoicesChecked": len(choices),
            "kernelsChecked": len(kernels), "plannedConstantsChecked": len(constants),
            "planSha256": artifact["manifest"]["planSha256"], "nativeResourceHashes": hashes}
