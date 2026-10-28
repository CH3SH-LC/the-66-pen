"""Build the provenance-bearing SQLite database and executable tool registry."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = ROOT / "data/miliastra-toolkit"
RUNTIME = ROOT / ".runtime/miliastra-toolkit"
MAP_DOCUMENT_SETS = {
    "map.floor": "floor-refinement",
    "map.reference": "reference-refinement",
    "map.street": "street-refinement",
}
SOURCES = [
    ("saved", "tools/miliastra-toolkit/saved.py"),
    ("live.discover", "tools/game-executor/discover_current_level.py"),
    ("scene.review", "tools/game-executor/orchestrate_write_review.py"),
    ("visual.window", "tools/miliastra-toolkit/window_capture.py"),
    ("helper", "tools/miliastra-toolkit/helper_cli.py"),
    ("runtime", "tools/game-executor/build_readonly_profile.py"),
    ("reference", "tools/mondstadt-reference/reference_cli.py"),
    ("author", "tools/authoring/author.py"),
    ("scene", "tools/game-executor/scene_cli.py"),
    ("scene_scale", "tools/game-executor/scene_scale.py"),
    ("node", "module:tools.node_workbench.__main__"),
    ("node_api", "tools/m2/node-capability/api/cli.py"),
    ("terrain", "tools/map-terrain/terrain_cli.py"),
    ("water", "tools/terrain-water/cli.py"),
    ("transform", "tools/entity-transform/cli.py"),
    ("material", "tools/entity-material/cli.py"),
    ("npc", "tools/npc-appearance/cli.py"),
    ("asset", "tools/game-executor/asset_inspection.py"),
    ("template", "tools/template-properties/cli.py"),
    ("template_v2", "tools/template-properties/v2/cli.py"),
    ("icons", "tools/template-properties/icons/cli.py"),
    ("world_frame", "tools/world-frame/cli.py"),
    ("playtest", "tools/playtest-control/cli.py"),
    ("gameplan", "module:tools.gameplan.cli"),
    ("native_tabs.prepare", "tools/game-executor/native-options/build_generalized.py"),
    ("native_tabs.verify", "tools/game-executor/native-options/verify_generalized_receipt.py"),
]
READ_ACTIONS = {"status", "capabilities", "decode", "physics-decode", "verify", "verify-save",
                "batch-status", "catalog", "lookup", "slots", "surfaces", "search", "show",
                "explain", "recipe", "edge", "value", "enums", "enum", "groups", "group",
                "route", "cluster", "example", "coverage", "resolve", "npc-records",
                "saved-readback", "inventory-diff", "template-plan", "plan", "merge"}
NATIVE_ACTIONS = {"dispatch", "execute", "control", "create", "creature-create", "create-batch",
                  "save", "reopen-current", "entity-create", "entity-inspect", "add", "wire",
                  "unwire", "build-print", "set", "condition", "count", "bind", "export",
                  "values", "build-plan", "install"}


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matches_prefix(name, prefixes):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def map_document_names(directory):
    return ("plan", "scene", "mesh-check") if directory == "floor-refinement" else ("plan", "scene", "placements", "check")


def confirmed_adjustments():
    path = ROOT / "data/codex-mondstadt/user-adjustments.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = {"rework", "floor-refinement", "reference-refinement", "street-refinement"}
    if value.get("userConfirmed") is not True or set(value.get("stages", {})) != expected:
        raise ValueError("USER_ADJUSTMENT_FOUR_CONFIRMED_STAGES_REQUIRED")
    for stage, evidence in value["stages"].items():
        if evidence["sceneSha256"] != sha(ROOT / f"data/codex-mondstadt/{stage}/scene.json"):
            raise ValueError("USER_ADJUSTMENT_STAGE_SOURCE_DRIFT:" + stage)
    return {"manifest": path.relative_to(ROOT).as_posix(), "manifestSha256": sha(path),
            "stages": value["stages"], "nativeCalledByAdoption": False,
            "runtimeCollisionVerified": False}


def registry(prefixes=(), *, persist=True):
    entries, excluded, failures = [], [], []
    if prefixes:
        old = json.loads((DATA / "tools.json").read_text(encoding="utf-8"))
        entries = [tool for tool in old["tools"] if not matches_prefix(tool["name"], prefixes)]
        excluded = old["excluded"]
    selected = []
    for prefix, source in SOURCES:
        path = ROOT / (source[7:].replace(".", "/") + ".py" if source.startswith("module:") else source)
        if path.is_file():
            selected.append((prefix, source))
        else:
            excluded.append({"source": source, "reason": "not-distributed-in-public-edition"})
    for prefix, source in (
        ("demo", "tools/codex-mondstadt-demo/demo.py"),
        ("demo.appearance", "tools/miliastra-toolkit/demo_appearance.py"),
        *((f"demo.play.{action}", "tools/codex-mondstadt-demo/play.py")
          for action in ("enter", "status", "move", "interact", "inventory", "full")),
        ("activities.build", "tools/codex-mondstadt-activities/activities.py"),
        ("activities.install", "tools/codex-mondstadt-activities/install.py"),
        ("activities.register_definitions", "tools/codex-mondstadt-activities/register_definitions.py"),
        ("activities.dependencies.sources", "tools/codex-mondstadt-activities/dependencies.py"),
        ("activities.dependencies.bag", "tools/codex-mondstadt-activities/dependencies.py"),
        ("activities.dependencies.properties", "tools/codex-mondstadt-activities/dependencies.py"),
        ("activities.verify", "tools/codex-mondstadt-activities/verify.py"),
        ("map.transform.verify_save", "tools/codex-mondstadt/verify_transform_save.py"),
        ("map.floor.prepare", "tools/codex-mondstadt/refine_floor.py"),
        ("map.floor.install", "tools/codex-mondstadt/refine_floor.py"),
        ("map.reference.prepare", "tools/codex-mondstadt/refine_reference_details.py"),
        ("map.reference.install", "tools/codex-mondstadt/refine_reference_details.py"),
        ("map.check", "tools/miliastra-toolkit/map_checks.py"),
        ("map.street.prepare", "tools/codex-mondstadt/refine_street_profiles.py"),
        ("map.street.install", "tools/codex-mondstadt/refine_street_profiles.py"),
        ("map.street.check", "tools/miliastra-toolkit/street_check.py"),
        ("map.user_adjustments.adopt", "tools/codex-mondstadt/adopt_confirmed_gate.py"),
        ("mondstadt.complete", "tools/codex-mondstadt/complete_demo.py"),
    ):
        if (ROOT / source).is_file():
            selected.append((prefix, source))
    if prefixes:
        selected = [(prefix, source) for prefix, source in selected if matches_prefix(prefix, prefixes)]
        if any(not any(matches_prefix(prefix, (requested,)) for prefix, _ in selected) for requested in prefixes):
            raise ValueError("REFRESH_PREFIX_HAS_NO_REGISTERED_SOURCE")
    for prefix, source in selected:
        call = subprocess.run([sys.executable, "-X", "utf8", "-B", str(HERE / "schema_capture.py"), source],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
        if call.returncode:
            failures.append({"source": source, "exitCode": call.returncode, "error": call.stderr[-2000:]})
            continue
        try:
            captured = json.loads(call.stdout)
        except ValueError:
            failures.append({"source": source, "error": "NON_JSON_CAPTURE", "stdout": call.stdout[-1000:]})
            continue
        for command in captured["commands"]:
            if command.get("excluded"):
                excluded.append(dict(source=source, **command))
                continue
            action = command["command"][-1] if command["command"] else "run"
            # Build/organize overwrite shared node catalogs and are not needed by callers.
            if prefix == "node" and action in ("build", "organize"):
                excluded.append({"source": source, "command": command["command"], "reason": "SHARED_CATALOG_OWNER"})
                continue
            native = prefix in ("scene",) or action in NATIVE_ACTIONS or "execute" in command["inputSchema"]["properties"]
            if prefix == "scene_scale" and action == "run":
                native = True
            if prefix == "live.discover":
                native = True
            if prefix == "scene.review":
                native = False
            if prefix == "transform" and action in ("inspect", "prepare", "set", "physics-inspect", "dispatch"):
                native = True  # These preparation commands optionally dispatch when a transport is supplied.
            if prefix == "asset" and action in ("sequence-run", "sequence-recover"):
                native = True
            if prefix in ("activities.install", "activities.register_definitions"):
                native = True
            if prefix in ("activities.dependencies.bag", "activities.dependencies.properties"):
                native = True
            if prefix == "author":
                native = action not in ("status", "capabilities")
            if prefix in ("node", "node_api", "npc", "icons", "world_frame"):
                native = False
            mutable = native and action not in ("inspect", "entity-inspect", "lookup", "catalog", "slots", "graph-status")
            if prefix == "helper":
                native, mutable = False, action != "status"
            if prefix == "node":
                mutable = False
            if prefix in ("map.floor.prepare", "map.reference.prepare", "map.check",
                          "map.street.prepare", "map.street.check"):
                native, mutable = False, False
            if prefix == "map.user_adjustments.adopt":
                native, mutable = False, True
            name = ".".join([prefix] + command["command"]).replace("-", "_")
            schema = command["inputSchema"]
            forced_defaults = {}
            if prefix in ("map.floor.install", "map.street.install"):
                # These production installers invoke this sibling through a string path.
                # Static Python-import discovery cannot see that subprocess dependency.
                verifier = next(tool for tool in entries if tool["name"] == "map.transform.verify_save")
                dependencies = {d["path"]: d for d in captured["codeDependencies"]}
                dependencies[verifier["source"]] = {
                    "path": verifier["source"], "sha256": verifier["sourceSha256"]}
                dependencies.update({d["path"]: d for d in verifier["codeDependencies"]})
                captured["codeDependencies"] = list(dependencies.values())
            if prefix == "mondstadt.complete":
                schema["properties"]["operation_id"]["pattern"] = "^[A-Za-z0-9_-]{1,40}$"
                forced_defaults["_timeout_seconds"] = 7200
                # This workflow delegates to fixed sibling CLIs through subprocess.
                dependencies = {d["path"]: d for d in captured["codeDependencies"]}
                for previous in entries:
                    if previous["name"].startswith(("demo.", "activities.", "map.")):
                        dependencies[previous["source"]] = {
                            "path": previous["source"], "sha256": previous["sourceSha256"]}
                        dependencies.update({d["path"]: d for d in previous["codeDependencies"]})
                captured["codeDependencies"] = list(dependencies.values())
            if prefix in ("map.floor.prepare", "map.reference.prepare", "map.street.prepare"):
                forced_defaults.update(prepare_only=True, execute=False)
                schema["properties"]["prepare_only"].update(enum=[True], default=True)
            if prefix == "map.floor.install":
                forced_defaults["prepare_only"] = False
                schema["properties"]["prepare_only"].update(enum=[False], default=False)
                schema["required"].extend(["city_run", "session", "gil"])
            if prefix == "map.reference.install":
                forced_defaults["prepare_only"] = False
                schema["properties"]["prepare_only"].update(enum=[False], default=False)
                schema["required"].extend(["floor_run", "session", "gil", "bridge_run_id"])
            if prefix == "map.street.install":
                forced_defaults["prepare_only"] = False
                schema["properties"]["prepare_only"].update(enum=[False], default=False)
                schema["required"].extend(["city_run", "session", "gil", "bridge_run_id"])
            if prefix == "activities.build":
                forced_defaults["command"] = "build"
                schema["properties"]["command"]["default"] = "build"
                schema["required"].remove("command")
            if prefix.startswith("activities.dependencies."):
                selection = prefix.rsplit(".", 1)[1]
                forced_defaults["command"] = selection
                schema["properties"]["command"].update(default=selection, enum=[selection])
                schema["required"].remove("command")
                if selection != "sources":
                    schema["required"].extend(["gil", "level_id", "session", "lease_holder"])
                    schema["properties"]["level_id"]["enum"] = [1073741845]
                    schema["required"].append("reviewed_source_set_sha256" if selection == "bag" else "definitions")
            if prefix.startswith("demo.play."):
                selection = prefix.rsplit(".", 1)[1]
                forced_defaults["action"] = selection
                schema["properties"]["action"].update(default=selection, enum=[selection])
                schema["required"].remove("action")
                schema["properties"]["operation_id"]["pattern"] = "^[A-Za-z0-9_-]{1,64}$"
                if selection == "move":
                    schema["required"].append("target")
                elif selection == "interact":
                    schema["required"].extend(["host_id", "label"])
                    schema["properties"]["host_id"]["minimum"] = 1
                    schema["properties"]["label"]["minLength"] = 1
                elif selection == "full":
                    schema["required"].extend(["scene", "manifest", "receipt", "activities", "activities_receipt"])
            if "execute" in schema["properties"]:
                # Execute tools execute. Use toolkit plan for an unexecuted argv.
                executes = prefix not in ("map.floor.prepare", "map.reference.prepare", "map.street.prepare")
                schema["properties"]["execute"].update(enum=[executes], default=executes)
                forced_defaults["execute"] = executes
            schema["properties"]["_timeout_seconds"] = {"type": "integer", "minimum": 1, "maximum": 1800, "default": 300}
            if prefix in ("map.street.install", "map.street.check"):
                forced_defaults["_timeout_seconds"] = 1800
                schema["properties"]["_timeout_seconds"]["default"] = 1800
            if prefix == "mondstadt.complete":
                schema["properties"]["_timeout_seconds"].update(maximum=7200, default=7200)
            if mutable:
                schema["properties"]["_operation_id"] = {
                    "type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$",
                    "description": "Unique one-shot operation identity. Repeated requests read the receipt; never re-dispatch."}
                schema["required"].append("_operation_id")
            description = command["description"].strip().split("\n")[0] or f"{prefix} {' '.join(command['command'])}"
            if prefix.startswith(("map.floor.", "map.reference.", "map.street.")):
                description = f"Fixed current Mondstadt scene (level 1073741845): {prefix.rsplit('.', 1)[1]}. Native application unverified."
            if prefix == "mondstadt.complete":
                description = "Execute the fixed level-1073741845 saved-checkpoint workflow once through real player settlement; native outcome and visual fidelity remain unverified until evidence."
            if prefix == "map.user_adjustments.adopt":
                description = "Adopt only the explicitly confirmed gate 1077939966 transform and wall 1077939912 deletion from the saved file; rebuild four plans offline once. Existing adoption refuses replay."
            if prefix == "map.transform.verify_save":
                description = "Read-only production save verification with the observed two-pair root46 shape. Requires exact transform/save receipts; reports unknown fields and allSaveDomainsVerified=false."
            command["description"] = description
            entries.append(dict(name=name,
                                source=captured["source"], sourceSha256=captured["sha256"],
                                codeDependencies=captured["codeDependencies"],
                                invocation=source, nativePossible=native, mutating=mutable,
                                forcedDefaults=forced_defaults,
                                runtimeVerified="unknown", **command))
    output = {"schemaVersion": 1, "tools": entries, "excluded": excluded, "captureFailures": failures,
              "captureDispatchPerformed": False}
    if persist and not failures:
        (DATA / "tools.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


class Builder:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE sources(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL);
        CREATE TABLE records(kind TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,
          category TEXT,search_text TEXT NOT NULL,payload TEXT NOT NULL,source TEXT NOT NULL,
          PRIMARY KEY(kind,id),FOREIGN KEY(source) REFERENCES sources(path));
        CREATE INDEX record_kind_category ON records(kind,category);
        CREATE TABLE entities(template_id INTEGER PRIMARY KEY,name TEXT,native_kind INTEGER,
          category TEXT,icon_path TEXT,dimensions_status TEXT,creation_status TEXT,payload TEXT NOT NULL);
        CREATE TABLE nodes(stable_key TEXT PRIMARY KEY,definition_id INTEGER,graph_kind INTEGER,
          name TEXT,family TEXT,payload TEXT NOT NULL);
        CREATE INDEX node_identity ON nodes(graph_kind,definition_id);
        CREATE TABLE ports(node_key TEXT,port_key TEXT,kind INTEGER,port_index INTEGER,
          name TEXT,server_param_type INTEGER,generic_id INTEGER,storage_kind INTEGER,payload TEXT NOT NULL,
          PRIMARY KEY(node_key,port_key),FOREIGN KEY(node_key) REFERENCES nodes(stable_key));
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        self.source_counts = {}

    def source(self, path):
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p
        relative = p.relative_to(ROOT).as_posix()
        self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?)", (relative, sha(p), p.stat().st_size))
        return relative

    def read(self, path):
        source = self.source(path)
        text = (ROOT / source).read_text(encoding="utf-8-sig")
        try:
            return json.loads(text), source
        except json.JSONDecodeError:
            return [json.loads(line) for line in text.splitlines() if line.strip()], source

    def record(self, kind, identity, name, category, value, source):
        text = dump(value)
        searchable = text if kind in ("gameplay", "map", "capability") else dump({
            "id": str(identity), "name": str(name), "category": str(category or ""),
            "keywords": value.get("keywords"), "description": value.get("description"),
            "menuPaths": value.get("menuPaths"), "source": source,
        })
        self.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?)",
                        (kind, str(identity), str(name), str(category or ""), searchable, text, source))

    def build(self, tools):
        names, ns = self.read("docs/research/entity-create/prefab-name-directory.json")
        assets, asset_source = self.read("data/m2/assets/prefab-catalog.json")
        assets_by_id = {str(x["templateId"]): x for x in assets["prefabs"]}
        icon_bundle = ROOT / ".runtime/verification/update-repair-20260925/catalog/assets-7.1/assets.dec"
        icon_source = self.source(icon_bundle) if icon_bundle.is_file() else None
        icon_entries = {}
        if icon_source:
            with zipfile.ZipFile(icon_bundle) as archive:
                icon_entries = {entry.filename: {"bytes": entry.file_size, "crc32": entry.CRC}
                                for entry in archive.infolist() if not entry.is_dir()}
        geometry = {}
        for path in sorted((ROOT / "data/mondstadt/reference3d/template-geometry-v1/templates").glob("*/geometry.json")):
            item, source = self.read(path)
            geometry[str(item["templateId"])] = (item, source)
        # Native category arrays are retained verbatim. The friendly category is curated and not relabelled native.
        for tid, name in names["names"].items():
            a = assets_by_id.get(str(tid), {})
            geo, gs = geometry.get(str(tid), ({}, None))
            bounds = geo.get("nonShadowEnabledStaticBounds")
            dimensions = {"status": "source-static-mesh" if bounds else "unknown",
                          "sizeXYZ": bounds.get("sizeXYZ") if bounds else None,
                          "bounds": bounds, "source": gs,
                          "scope": geo.get("boundsScope"),
                          "staticGeometryComplete": geo.get("staticGeometryComplete"),
                          "runtimeRendererBoundsVerified": geo.get("runtimeRendererBoundsVerified", False),
                          "runtimeColliderBoundsVerified": geo.get("runtimeColliderBoundsVerified", False)}
            entity = {"templateId": int(tid), "name": name,
                      "nativeKind": a.get("nativeKind"), "nativeCategories": a.get("categories"),
                      "nativeCategoryStatus": "recorded" if a.get("categories") else "unknown",
                      "curatedCategory": a.get("category"), "family": a.get("family"),
                      "icon": {"resourcePath": a.get("iconPath"), "source": asset_source,
                               "bundleSource": icon_source,
                               "bundleMember": icon_entries.get(a.get("iconPath")),
                               "imageAvailability": "present-in-captured-native-bundle" if a.get("iconPath") in icon_entries else "unknown",
                               "visualVerified": False},
                      "dimensions": dimensions,
                      "creation": {"tool": "scene.create", "batchTool": "scene.create_batch",
                                   "creatureTool": "scene.creature_create",
                                   "templateId": int(tid), "acceptedByCli": True,
                                   "runtimeCreationVerified": "unknown",
                                   "requires": ["current session", "fresh baseline", "coordinator review", "helper queue"]},
                      "provenance": [{"source": ns, "locator": f"names.{tid}"},
                                     {"source": asset_source, "locator": f"prefabs[templateId={tid}]"}]}
            self.record("entity", tid, name, a.get("category"), entity, ns)
            self.db.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
                            (int(tid), name, a.get("nativeKind"), a.get("category"),
                             a.get("iconPath"), dimensions["status"], "runtime-unknown", dump(entity)))
        catalog, source = self.read("data/node-workbench/catalog.json")
        for node in catalog["nodes"]:
            self.record("node", node["key"], node["name"], str(node["graphKind"]), node, source)
            self.db.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?)",
                            (node["key"], node["definitionId"], node["graphKind"], node["name"], node["family"], dump(node)))
            for port in node["ports"]:
                desc = port.get("descriptor") or {}
                live = port.get("live") or {}
                self.db.execute("INSERT INTO ports VALUES (?,?,?,?,?,?,?,?,?)",
                                (node["key"], port["key"], port["kind"], port["index"], port.get("name", ""),
                                 live.get("serverParamType"), live.get("fbGKY8GZn68"), desc.get("storageKind"), dump(port)))
        for key, enum in catalog["enumGroups"].items():
            self.record("enum", key, enum.get("name", key), "native-enumeration", enum, source)
        for path in sorted((ROOT / "data/node-contracts/variants").glob("*/*.json")):
            items, source = self.read(path)
            for item in items:
                self.record("node_contract", item["contractId"], item["name"],
                            str(item["graphKindRaw"]), item, source)
        for path in sorted((ROOT / "data/m2/reference-pack/map").glob("*.json")):
            item, source = self.read(path)
            self.record("map_document", path.stem, path.stem, "reference-pack", item, source)
            for i, record in enumerate(item.get("records", [])):
                self.record("map", f"{path.stem}:{record.get('id', i)}",
                            record.get("nameZh", record.get("id", str(i))), path.stem, record, source)
        for path in sorted((ROOT / "data/m2/reference-pack/content").glob("*.json")):
            item, source = self.read(path)
            for i, record in enumerate(item.get("records", [])):
                identity = record.get("id", str(i))
                name = record.get("nameZh") or (record.get("dish") or {}).get("nameZh") or identity
                self.record("gameplay", f"{path.stem}:{identity}", name, path.stem, record, source)
        for path in [
            "data/mondstadt/world-contract.json", "data/mondstadt/outside/terrain/shared-transform.json",
            "data/m2/terrain/manifest.json", "data/m2/terrain/y-calibration.json",
            "data/m2/terrain/ground-height.json", "data/m2/reference-pack/sources.json",
            "data/m2/reference-pack/unknowns.json", "data/level-index.json",
        ]:
            if (ROOT / path).is_file():
                item, source = self.read(path)
                self.record("map_document", path, Path(path).stem, "source-evidence", item, source)
        for directory in MAP_DOCUMENT_SETS.values():
            for name in map_document_names(directory):
                path = f"data/codex-mondstadt/{directory}/{name}.json"
                if (ROOT / path).is_file():
                    item, source = self.read(path)
                    self.record("map_document", path, directory + ":" + name,
                                "planned-" + directory, item, source)
        adjustments = confirmed_adjustments()
        if adjustments:
            for path in (adjustments["manifest"], "data/codex-mondstadt/rework/scene.json"):
                item, source = self.read(path)
                self.record("map_document", path, Path(path).stem,
                            "confirmed-user-adjustments", item, source)
        capability, source = self.read("tools/authoring/interface_inventory.json")
        for item in capability["capabilities"]:
            item = dict(item, evidenceFreshness="historical-source-snapshot", runtimeVerified="unknown")
            self.record("capability", item["id"], item["title"], item["status"], item, source)
        source = self.source(DATA / "tools.json")
        for tool in tools["tools"]:
            self.record("tool", tool["name"], tool["name"], tool["name"].split(".")[0], tool, source)
            self.source(tool["source"])
            for dependency in tool["codeDependencies"]:
                self.source(dependency["path"])
        import toolkit
        builtin_source = self.source(HERE / "toolkit.py")
        for name, (description, schema) in toolkit.BUILTINS.items():
            self.record("tool", name, name, "builtin",
                        {"name": name, "description": description, "inputSchema": schema,
                         "source": builtin_source, "runtimeVerified": False}, builtin_source)
        official, source = [], None  # Raw official prefab resources are not distributed.
        for item in official:
            self.record("prefab_resource", item["source_relative_path"], item["source_relative_path"],
                        "official-decoded-resource", item, source)
        for path in sorted((DATA / "recipes").glob("*.json")):
            item, source = self.read(path)
            self.record("recipe", item["id"], item["name"], "executable-workflow", item, source)
        for path in sorted(HERE.glob("*.py")):
            self.source(path)
        self.source(HERE / "README.md")
        counts = dict(self.db.execute("SELECT kind,count(*) FROM records GROUP BY kind"))
        summary = {"schemaVersion": 1, "builtAtUtc": datetime.now(timezone.utc).isoformat(),
                   "counts": counts, "ports": self.db.execute("SELECT count(*) FROM ports").fetchone()[0],
                   "sourceFiles": self.db.execute("SELECT count(*) FROM sources").fetchone()[0],
                   "productionToolCount": len(tools["tools"]), "builtinToolCount": len(toolkit.BUILTINS),
                   "aiToolCount": len(tools["tools"]) + len(toolkit.BUILTINS),
                   "dimensionsKnown": len(geometry), "runtimeVerified": False,
                   "nativeIconMembersPresent": sum(a.get("iconPath") in icon_entries for a in assets["prefabs"]),
                   "limits": ["All counts describe imported local evidence, not all game capabilities.",
                              "Entity bounds are static source geometry, not verified runtime collision bounds.",
                              "Item IDs inside gameplay references are scoped to their recorded level and save hash.",
                              "Native categories that were not observed remain unknown.",
                              "Historical level-index is never used to select the current level."]}
        if adjustments:
            summary["confirmedUserAdjustments"] = adjustments
        self.db.execute("INSERT INTO metadata VALUES (?,?)", ("build", dump(summary)))
        self.db.commit()
        integrity = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(integrity)
        self.db.close()
        return summary


def refresh(prefixes):
    """Update selected executable contracts while reusing the existing data tables."""
    previous_hash = sha(DATA / "catalog.sqlite")
    tools = registry(prefixes, persist=False)
    if tools["captureFailures"]:
        raise ValueError("REFRESH_CAPTURE_FAILED:" + dump(tools["captureFailures"]))
    selected = [tool for tool in tools["tools"] if matches_prefix(tool["name"], prefixes)]
    encoded_tools = json.dumps(tools, ensure_ascii=False, indent=2).encode("utf-8")
    target = DATA / "catalog.sqlite"
    temp = DATA / "catalog.refreshing.sqlite"
    shutil.copy2(target, temp)
    with closing(sqlite3.connect(temp)) as db:
        def source(path, expected=None):
            path = Path(path)
            if not path.is_absolute():
                path = ROOT / path
            actual = sha(path)
            if expected is not None and actual != expected:
                raise ValueError("REFRESH_SOURCE_CHANGED:" + str(path))
            relative = path.relative_to(ROOT).as_posix()
            db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                       (relative, actual, path.stat().st_size))
            return relative
        for existing in json.loads((DATA / "tools.json").read_text(encoding="utf-8"))["tools"]:
            if matches_prefix(existing["name"], prefixes):
                db.execute("DELETE FROM records WHERE kind='tool' AND id=?", (existing["name"],))
        for tool in selected:
            source(tool["source"], tool["sourceSha256"])
            for dependency in tool["codeDependencies"]:
                source(dependency["path"], dependency["sha256"])
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?)",
                       ("tool", tool["name"], tool["name"], tool["name"].split(".")[0],
                        dump({"id": tool["name"], "name": tool["name"]}), dump(tool),
                        "data/miliastra-toolkit/tools.json"))
        for path in sorted(HERE.glob("*.py")):
            source(path)
        source(HERE / "README.md")
        db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                   ("data/miliastra-toolkit/tools.json", hashlib.sha256(encoded_tools).hexdigest(),
                    len(encoded_tools)))
        documents = []
        for family, directory in MAP_DOCUMENT_SETS.items():
            if not any(matches_prefix(family, (prefix,)) or matches_prefix(prefix, (family,))
                       for prefix in prefixes):
                continue
            for name in map_document_names(directory):
                path = ROOT / f"data/codex-mondstadt/{directory}/{name}.json"
                relative = source(path)
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?)",
                           ("map_document", relative, directory + ":" + name,
                            "planned-" + directory, relative, dump(value), relative))
                documents.append(relative)
        adjustments = None
        if any(matches_prefix("map.user_adjustments", (prefix,)) or
               matches_prefix(prefix, ("map.user_adjustments",)) for prefix in prefixes):
            adjustments = confirmed_adjustments()
            if adjustments is None:
                raise ValueError("USER_ADJUSTMENT_MANIFEST_REQUIRED")
            for relative in (adjustments["manifest"], "data/codex-mondstadt/rework/scene.json"):
                source(relative)
                value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?)",
                           ("map_document", relative, Path(relative).stem, "confirmed-user-adjustments",
                            relative, dump(value), relative))
                documents.append(relative)
        summary = json.loads(db.execute("SELECT value FROM metadata WHERE key='build'").fetchone()[0])
        summary.update(builtAtUtc=datetime.now(timezone.utc).isoformat(),
                       counts=dict(db.execute("SELECT kind,count(*) FROM records GROUP BY kind")),
                       sourceFiles=db.execute("SELECT count(*) FROM sources").fetchone()[0],
                       productionToolCount=len(tools["tools"]),
                       aiToolCount=len(tools["tools"]) + summary["builtinToolCount"],
                       incrementalRefresh={"prefixes": list(prefixes), "previousDatabaseSha256": previous_hash,
                                           "toolRecordsUpdated": [tool["name"] for tool in selected],
                                           "mapDocumentsUpdated": documents,
                                           "entityNodePortTablesReused": True})
        if adjustments:
            summary["confirmedUserAdjustments"] = adjustments
        db.execute("UPDATE metadata SET value=? WHERE key='build'", (dump(summary),))
        db.commit()
    (DATA / "tools.json").write_bytes(encoded_tools)
    temp.replace(target)
    summary.update(database=target.relative_to(ROOT).as_posix(), databaseSha256=sha(target), toolCount=len(tools["tools"]),
                   captureFailures=[], excludedTools=tools["excluded"])
    (DATA / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-prefix", action="append", default=[],
                        help="Refresh only selected tool families; reuse entity/node/port tables.")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    # Generate every recipe from the shipped technical catalog, never a private snapshot.
    sys.path.insert(0, str(ROOT))
    from tools.node_workbench.catalog import Catalog
    from tools.node_workbench.recipes import recipe
    node_catalog = Catalog()
    recipe_path = ROOT / "data/node-workbench/recipes.json"
    encoded = json.dumps([recipe(node_catalog, n["graphKind"], n["definitionId"])
                          for n in node_catalog.nodes], ensure_ascii=False, indent=1)
    if not recipe_path.exists() or recipe_path.read_text(encoding="utf-8") != encoded:
        recipe_path.write_text(encoded, encoding="utf-8")
    if args.refresh_prefix:
        print(json.dumps(refresh(args.refresh_prefix), ensure_ascii=False, indent=2))
        return 0
    tools = registry()
    if tools["captureFailures"]:
        print(json.dumps({"ok": False, "captureFailures": tools["captureFailures"],
                          "previousRegistryPreserved": True}, ensure_ascii=False))
        return 1
    temp = DATA / "catalog.building.sqlite"
    if temp.exists():
        temp.unlink()
    summary = Builder(temp).build(tools)
    target = DATA / "catalog.sqlite"
    temp.replace(target)
    summary.update(database=target.relative_to(ROOT).as_posix(), databaseSha256=sha(target),
                   toolCount=len(tools["tools"]), captureFailures=tools["captureFailures"],
                   excludedTools=tools["excluded"])
    (DATA / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if tools["captureFailures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
