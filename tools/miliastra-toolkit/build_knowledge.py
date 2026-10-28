"""Incremental inventory builder. Imports no investigated scripts; never opens the game."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ai-workbench"
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "bin", "obj",
        "ai-workbench", "contract-staging"}
SCOPES = ["AI-START-HERE.md", "ai.py", "pen.py", "tools", "docs", "data", "catalog"]
RUNTIME_NAMES = re.compile(r"(?:audit|receipt|result|manifest|execution|progress|index|status|termination|error|summary|\.png$|\.jpg$)", re.I)
EXTENSIONS = {".py", ".ps1", ".cs", ".cpp", ".h", ".json", ".jsonl", ".md", ".txt",
              ".yaml", ".yml", ".toml", ".png", ".jpg", ".jpeg", ".webp", ".obj",
              ".glb", ".gltf", ".fbx", ".blend", ".csv", ".sqlite", ".zip",
              ".npz", ".npy", ".mtl", ".dds", ".ktx2", ".wav", ".ogg", ".mp4", ".webm", ".mihoyobin"}
LIBRARIES = [
    ("templates", "模板名称、分类、图标", "data/m2/assets/prefab-catalog.json", "entity"),
    ("nodes", "节点定义、端口、枚举", "data/node-workbench/catalog.json", "node"),
    ("node-recipes", "逐变体节点操作配方", "data/node-workbench/recipes.json", "node"),
    ("node-contracts", "节点合同与未知字段", "data/node-contracts/index.json", "node"),
    ("reference-pack", "地形、水、道具、玩法参考", "data/m2/reference-pack/pack.json", "map"),
    ("template-geometry", "模板尺寸和几何", "data/mondstadt/reference3d/template-geometry-v1", "geometry"),
    ("prefab-originals", "官方预制体原件", ".runtime/mondstadt/rework-20261017/shared-source/official-prefab-index.json", "prefab"),
    ("native-icons", "官方图标资源容器", ".runtime/verification/update-repair-20260925/catalog/assets-7.1/assets.dec", "icons"),
    ("recent-reference", "本次蒙德视觉与修正素材", "data/codex-main-street", "reference"),
    ("materials", "材质参数与写入合同", "tools/entity-material", "material"),
    ("terrain", "地形块和采样工具", "tools/map-terrain", "terrain"),
    ("water", "水面与边界工具", "tools/terrain-water", "water"),
    ("npc", "NPC与生物外观资料", "tools/npc-appearance", "npc"),
    ("playtest", "试玩、移动、交互工具", "tools/playtest-control", "playtest"),
    ("kb", "公开研究与故障处理", "docs/history", "methods"),
]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def paths():
    """No recursive traversal of native candidate copies or vendor trees."""
    for scope in SCOPES:
        base = ROOT / scope
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and
                             not d.startswith(("candidate-source", "node_modules")))
            for name in sorted(files):
                path = Path(folder) / name
                if path.suffix.lower() not in EXTENSIONS or path.is_symlink():
                    continue
                if scope.startswith(".runtime") and not RUNTIME_NAMES.search(name):
                    continue
                if scope == "data" and "miliastra-toolkit" in path.parts:
                    continue  # Imported as structured records below, not duplicated.
                yield path


def unknowns(value):
    if isinstance(value, dict):
        return sum(unknowns(x) for x in value.values())
    if isinstance(value, list):
        return sum(unknowns(x) for x in value)
    return int(value in ("unknown", "unverified") if isinstance(value, str) else False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    start = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "inventory-cache.json"
    old = read(cache_path) if cache_path.exists() and not args.force else {}
    registry = read(ROOT / "data/miliastra-toolkit/tools.json")
    import toolkit
    write(OUT / "tool-schemas.json", {"tools": toolkit.tool_list(), "nativeCalled": False})
    tool_sources = {t["source"].replace("\\", "/"): [] for t in registry["tools"]}
    for t in registry["tools"]:
        tool_sources.setdefault(t["source"].replace("\\", "/"), []).append(t["name"])
    cache, errors, files, changed = {}, [], [], 0
    for path in paths():
        rel = path.relative_to(ROOT).as_posix()
        st = path.stat()
        key = [st.st_size, st.st_mtime_ns]
        previous = old.get(rel)
        if previous and previous["stat"] == key:
            item = previous
            if path.suffix == ".py" and "calls" not in item and st.st_size <= 2*1024*1024:
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                    item["calls"] = sorted({ast.unparse(n.func) for n in ast.walk(tree)
                                            if isinstance(n, ast.Call)})[:400]
                except SyntaxError:
                    pass
        else:
            changed += 1
            item = {"path": rel, "stat": key, "bytes": st.st_size,
                    "sha256": sha(path) if st.st_size <= 64*1024*1024 else None,
                    "hashState": "content" if st.st_size <= 64*1024*1024 else "large-file-index-only"}
            if path.suffix.lower() in {".py", ".ps1", ".cs", ".cpp", ".h", ".md", ".txt", ".json"} and st.st_size <= 2*1024*1024:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                item["summary"] = " ".join(text[:1500].split())[:900]
                item["errorCodes"] = sorted(set(re.findall(r"""['"]([A-Z][A-Z0-9_]{7,90})[:'"]""", text)))[:250]
                item["levelCoupling"] = sorted(set(re.findall(r"\b10737418\d{2}\b", text)))
                if path.suffix == ".py":
                    try:
                        tree = ast.parse(text)
                        item["functions"] = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        item["entrypoint"] = "__main__" in text or "ArgumentParser(" in text
                        item["cliOptions"] = sorted(set(re.findall(r"""['"](--[a-z][a-z0-9-]+)['"]""", text)))
                        item["calls"] = sorted({ast.unparse(n.func) for n in ast.walk(tree)
                                                if isinstance(n, ast.Call)})[:400]
                    except SyntaxError as exc:
                        item["parseError"] = str(exc)
                        errors.append({"source": rel, "error": str(exc)})
        cache[rel] = item
        files.append(item)
    # Reuse a fully identical index. Volatile .runtime receipts are detected by stat.
    fingerprint = hashlib.sha256(dump({
        "files": {k: v["stat"] for k, v in cache.items()},
        "registry": sha(ROOT / "data/miliastra-toolkit/tools.json"),
        "builder": sha(Path(__file__)),
        "workflows": sha(OUT / "workflows.json"), "errors": sha(OUT / "errors.json")
    }).encode()).hexdigest()
    previous_report = read(OUT / "coverage.json") if (OUT / "coverage.json").exists() else {}
    if not args.force and fingerprint == previous_report.get("inputFingerprint") and (OUT / "knowledge.sqlite").exists():
        print(dump({"ok": True, "reused": True, "files": len(files), "changedFiles": 0,
                    "seconds": round(time.monotonic()-start, 3), "nativeCalled": False}))
        return 0
    temporary = OUT / "knowledge.building.sqlite"
    if temporary.exists():
        temporary.unlink()
    con = sqlite3.connect(temporary)
    con.executescript("""
    CREATE TABLE entries(id TEXT PRIMARY KEY,kind TEXT,name TEXT,source TEXT,summary TEXT,search TEXT,payload TEXT);
    CREATE INDEX entry_kind ON entries(kind,id);
    CREATE TABLE node_keys(id TEXT PRIMARY KEY,definition_id INTEGER,graph_kind INTEGER);
    CREATE INDEX node_identity ON node_keys(definition_id,graph_kind);
    """)
    counts = Counter()
    def add(kind, ident, name, source, payload, summary=""):
        identity = kind + ":" + str(ident)
        con.execute("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?)", (
            identity, kind, name, source, summary[:900],
            " ".join([str(ident), name, source, summary])[:12000], dump(payload)))
        counts[kind] += 1
        return identity
    scripts = []
    for f in files:
        path = f["path"]
        add("file", path, Path(path).name, path, f, f.get("summary", path))
        if f.get("entrypoint"):
            registered = tool_sources.get(path, [])
            item = dict(f, registeredTools=registered, dispatchable=bool(registered),
                        scope="scene-specific" if f.get("levelCoupling") else "source-inspection-required",
                        runtimeVerified=False)
            joined = path + " " + " ".join(f.get("calls", []))
            routes = {
                "scene": ("scene_cli", "job.write", "create_batch", "create-batch", "install."),
                "transform": ("transform", "reparent", "assembly", "assembly_"),
                "material": ("material",), "terrain": ("terrain",), "water": ("water",),
                "author": ("graph", "node", "binding"), "visual.window": ("capture", "screenshot"),
                "asset": ("asset", "template", "geometry"), "reference": ("reference", "registration"),
                "helper": ("helper", "elevated", "queue"), "playtest": ("playtest", "trial", "interaction"),
            }
            item["candidateReplacementFamilies"] = [family for family, hints in routes.items()
                                                     if any(s in joined for s in hints)]
            item["replacementEvidence"] = "source-name-and-call-reference-routing; read exact contract before execution"
            scripts.append(item)
            add("script", path, Path(path).stem, path, item, f.get("summary", ""))
        if path.endswith(".md"):
            add("method", path, Path(path).stem, path, dict(f, evidence="source-document"),
                f.get("summary", ""))
        for code in f.get("errorCodes", []):
            add("error", code + ":" + path, code, path,
                {"code": code, "source": path, "recoveryTool": "knowledge.errors"}, code)
    for t in registry["tools"]:
        add("tool", t["name"], t["name"], t["source"], t, t["description"])
    assets = read(ROOT / "data/m2/assets/prefab-catalog.json")["prefabs"]
    duplicates = Counter(p.get("nameZh", "") for p in assets)
    with sqlite3.connect(ROOT / "data/miliastra-toolkit/catalog.sqlite") as catalog_db:
        detailed_assets = {row[0]: json.loads(row[1]) for row in catalog_db.execute("SELECT template_id,payload FROM entities")}
    asset_coverage = []
    for asset in assets:
        detail = detailed_assets.get(asset["templateId"], {})
        row = {"templateId": asset["templateId"], "name": asset.get("nameZh", ""),
               "uniqueName": bool(asset.get("nameZh")) and duplicates[asset.get("nameZh", "")] == 1,
               "dimensions": detail.get("dimensions", {}),
               "iconAvailability": detail.get("icon", {}).get("imageAvailability", "unknown"),
               "runtimeCreationVerified": detail.get("creation", {}).get("runtimeCreationVerified", "unknown")}
        asset_coverage.append(row)
        add("asset", asset["templateId"], asset.get("nameZh", ""), "data/m2/assets/prefab-catalog.json",
            dict(asset, coverage=row, detailedRecord=detail, uniqueName=row["uniqueName"],
                 placementVerified=False, geometryTool="catalog.get", evidence="decoded-template-catalog"),
            dump({k: asset.get(k) for k in ("family", "category", "nativeKind", "iconPath")}))
    catalog = read(ROOT / "data/node-workbench/catalog.json")
    recipes = {v["definitionKey"]: v for v in read(ROOT / "data/node-workbench/recipes.json")}
    contracts = {}
    for path in sorted((ROOT / "data/node-contracts/variants").rglob("*.json")):
        for contract in read(path):
            k = contract["stableKey"]
            contracts.setdefault((k["definitionId"], contract["graphKindRaw"]), []).append(
                {"source": path.relative_to(ROOT).as_posix(), "contract": contract})
    node_gaps, node_rows = [], []
    for n in catalog["nodes"]:
        recipe = recipes.get(n["key"])
        matches = contracts.get((n["definitionId"], n["graphKind"]), [])
        # Definition and graph kind are necessary but not sufficient: category variant matters.
        matches = [m for m in matches if m["contract"]["stableKey"]["categoryVariant"] == n["category"]]
        unknown = sum(unknowns(x["contract"]) for x in matches)
        gap = {"key": n["key"], "definitionId": n["definitionId"], "graphKind": n["graphKind"],
               "recipePresent": recipe is not None, "contractCount": len(matches),
               "unknownFields": unknown, "runtimeVerified": n.get("runtimeVerified") is True}
        node_rows.append(gap)
        if not recipe or len(matches) != 1 or unknown or not gap["runtimeVerified"]:
            node_gaps.append(gap)
        payload = {"node": n, "recipe": recipe, "contracts": matches, "coverage": gap,
                   "doNotGuess": ["动态端口先读取实例 slots", "先选择 graphKind 再选 definitionId",
                                  "unknown 不是默认值", "保存读回不能代替试玩"],
                   "nextTools": ["graph.compile", "node.recipe", "node.edge", "node.value"]}
        ident = add("node", n["key"], n["name"], "data/node-workbench/catalog.json",
                    payload, n["name"] + " " + n.get("family", "") + " " + str(n["definitionId"]))
        con.execute("INSERT INTO node_keys VALUES (?,?,?)", (ident, n["definitionId"], n["graphKind"]))
    libraries = []
    for ident, label, source, domain in LIBRARIES:
        p = ROOT / source
        related = [f["path"] for f in files if f["path"] == source or f["path"].startswith(source.rstrip("/") + "/")]
        record = {"id": ident, "name": label, "domain": domain, "source": source,
                  "exists": p.exists(), "indexedFileCount": len(related),
                  "status": "present-source-scope-only" if p.exists() else "missing",
                  "guarantees": "目录存在不证明完整提取、尺寸精确或真机可用"}
        libraries.append(record)
        add("library", ident, label, source, record, label + " " + domain)
    con.commit()
    con.close()
    temporary.replace(OUT / "knowledge.sqlite")
    write(cache_path, cache)
    write(OUT / "node-coverage.json", {"variants": node_rows, "gaps": node_gaps})
    write(OUT / "script-coverage.json", {"scripts": scripts,
          "unregistered": [s["path"] for s in scripts if not s["dispatchable"]]})
    write(OUT / "asset-libraries.json", libraries)
    write(OUT / "asset-coverage.json", asset_coverage)
    report = {
        "schemaVersion": 1, "builtAtUtc": datetime.now(timezone.utc).isoformat(),
        "inputFingerprint": fingerprint, "counts": dict(counts), "sourceFiles": len(files),
        "changedFiles": changed, "librariesPresent": sum(x["exists"] for x in libraries),
        "librariesExpected": len(libraries), "missingLibraries": [x["id"] for x in libraries if not x["exists"]],
        "nodes": {"definitions": len({n["definitionId"] for n in catalog["nodes"]}),
                  "variants": len(node_rows), "recipes": sum(n["recipePresent"] for n in node_rows),
                  "uniqueContracts": sum(n["contractCount"] == 1 for n in node_rows),
                  "unknownFields": sum(n["unknownFields"] for n in node_rows),
                  "runtimeVerified": sum(n["runtimeVerified"] for n in node_rows)},
        "assets": {"templates": len(asset_coverage),
                   "dimensionsKnown": sum(x["dimensions"].get("status") != "unknown" and bool(x["dimensions"]) for x in asset_coverage),
                   "iconsPresentInRecordedBundle": sum(x["iconAvailability"] == "present-in-captured-native-bundle" for x in asset_coverage),
                   "ambiguousOrEmptyNames": sum(not x["uniqueName"] for x in asset_coverage)},
        "scripts": {"entrypoints": len(scripts), "registeredSources": sum(s["dispatchable"] for s in scripts),
                    "unregisteredSources": sum(not s["dispatchable"] for s in scripts)},
        "productionTools": len(registry["tools"]), "parseErrors": errors,
        "largeFilesIndexedWithoutContentHash": [f["path"] for f in files if not f.get("sha256")],
        "scope": SCOPES, "excluded": sorted(SKIP),
        "limitations": ["所有覆盖数字以列出的源集合为分母，不代表游戏内部全部素材或全部可操作功能。",
                       "未登记源码仅可查询，不被导入执行；固定场景脚本不能换档直接运行。",
                       "runtime 历史证据不代表当前游戏状态；本次构建没有游戏调用。",
                       "大文件保留位置、尺寸和时间，需按需工具验证内容；目录外运行记录未全量扫描。"],
        "databaseSha256": sha(OUT / "knowledge.sqlite"), "nativeCalled": False,
        "seconds": round(time.monotonic() - start, 3)}
    write(OUT / "coverage.json", report)
    print(dump(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
