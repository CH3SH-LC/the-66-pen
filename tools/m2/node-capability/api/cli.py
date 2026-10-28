#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""node-capability-api CLI（node-capability 模块 D4 冻结接口）。

脚本 / agent 直接调用的稳定 JSON 查询入口。六个子命令：
  query   --definition-id ID --graph-kind GK     精确取能力记录
  search  --query 中文关键词 [--graph-kind GK]   按名称 / 功能簇别名 / 原生菜单叶子检索
  ports   --definition-id ID --graph-kind GK     取端口表
  enums   --enum-id ID | --query 文本            取枚举表与真实选项
  cluster 功能簇id [--graph-kind GK]             列出功能簇内节点
  version                                       来源 sha256 + 810/929/4637/103 计数

退出码：0 命中；2 未找到（stdout 仍为 JSON 错误体）；3 参数错误；
1 仅用于数据缺失 / 完整性失败等内部错误（正常契约外，仍输出 JSON）。

确定性：不写 wall-clock、不用随机数；输出 json.dumps(ensure_ascii=False,
sort_keys=True, separators=(",", ":"))，同一查询逐字节一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_NOT_FOUND = 2
EXIT_ARGUMENT = 3

COMMANDS = ("query", "search", "ports", "enums", "cluster", "version", "graph-built")

MANIFEST_REL = Path("data/m2/node-capability/manifest")
DISCOVERY_REL = Path("data/node-workbench/discovery")
GRAPH_BUILT_REL = Path("data/m2/node-capability/evidence/graph-built-index.json")

MAX_SEARCH_LIMIT = 500
MAX_ENUM_LIMIT = 200
MAX_CLUSTER_LIMIT = 500


# ---------------------------------------------------------------------------
# 错误与输出
# ---------------------------------------------------------------------------


class CliError(Exception):
    """带退出码与可行动信息的 CLI 错误（最终都序列化为 stdout JSON）。"""

    def __init__(
        self,
        code: str,
        message: str,
        exit_code: int,
        query: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        command: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.query = {} if query is None else query
        self.extra = {} if extra is None else extra
        self.command = command
        self.hint = hint


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def emit(obj: dict[str, Any]) -> None:
    """一次性写出 UTF-8 JSON + 单个换行；绕过平台换行转换，保证字节稳定。"""
    data = (dumps(obj) + "\n").encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # pragma: no cover - 仅用于被测试代码替换 sys.stdout 的场景
        sys.stdout.write(data.decode("utf-8"))
        sys.stdout.flush()


def success(command: str, **fields: Any) -> int:
    body: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "command": command,
    }
    body.update(fields)
    emit(body)
    return EXIT_OK


def fail(exc: CliError) -> int:
    error: dict[str, Any] = {
        "code": exc.code,
        "message": exc.message,
        "query": exc.query,
    }
    if exc.hint:
        error["hint"] = exc.hint
    body: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "ok": False,
        "command": exc.command,
        "error": error,
    }
    body.update(exc.extra)
    emit(body)
    return exc.exit_code


# ---------------------------------------------------------------------------
# 路径与数据加载（只读复用台账，绝不写输入）
# ---------------------------------------------------------------------------

_ROOT: Path | None = None
_JSON_CACHE: dict[str, Any] = {}
_SHARD_ENTRY_CACHE: dict[str, dict[int, dict[str, Any]]] = {}
_ROUTES_BY_KEY: dict[tuple[int, int], dict[str, Any]] | None = None
_CLUSTER_MEMBERS_CACHE: dict[str, tuple[tuple[int, int], ...]] = {}
_CLUSTERS_BY_VARIANT: dict[tuple[int, int], list[str]] | None = None


def repo_root() -> Path:
    global _ROOT
    if _ROOT is None:
        here = Path(__file__).resolve()
        for base in here.parents:
            if (base / MANIFEST_REL / "index.json").is_file():
                _ROOT = base
                break
        else:
            raise CliError(
                "DATA_NOT_FOUND",
                "找不到仓库根：从 cli.py 向上没有发现 "
                f"{MANIFEST_REL.as_posix()}/index.json；请在完整仓库布局中运行，"
                "或先构建 node-capability-manifest。",
                EXIT_INTERNAL,
                {"cliPath": here.as_posix()},
            )
    return _ROOT


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root()).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> Any:
    key = path.resolve().as_posix()
    if key in _JSON_CACHE:
        return _JSON_CACHE[key]
    if not path.is_file():
        raise CliError(
            "DATA_NOT_FOUND",
            f"只读输入缺失：{rel_path(path)}；请先运行 node-capability-manifest 的 build.py。",
            EXIT_INTERNAL,
            {"path": rel_path(path)},
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise CliError(
            "DATA_INTEGRITY",
            f"只读输入不是合法 JSON：{rel_path(path)}（{exc.msg}，行 {exc.lineno} 列 {exc.colno}）。",
            EXIT_INTERNAL,
            {"path": rel_path(path)},
        ) from exc
    _JSON_CACHE[key] = data
    return data


def manifest_dir() -> Path:
    return repo_root() / MANIFEST_REL


def discovery_dir() -> Path:
    return repo_root() / DISCOVERY_REL


def manifest_index() -> dict[str, Any]:
    return load_json(manifest_dir() / "index.json")


def shard_path(shard_rel: str) -> Path:
    """index.json 的定义项用 'shard-NN.json'，artifacts 用 'shards/shard-NN.json'。"""
    candidate = manifest_dir() / shard_rel
    if candidate.is_file():
        return candidate
    return manifest_dir() / "shards" / shard_rel


def enums_data() -> dict[str, Any]:
    return load_json(manifest_dir() / "enums.json")


def discovery_index() -> dict[str, Any]:
    return load_json(discovery_dir() / "index.json")


def discovery_routes() -> list[dict[str, Any]]:
    return load_json(discovery_dir() / "routes.json")


def routes_by_key() -> dict[tuple[int, int], dict[str, Any]]:
    global _ROUTES_BY_KEY
    if _ROUTES_BY_KEY is None:
        _ROUTES_BY_KEY = {
            (int(route["definitionId"]), int(route["graphKind"])): route
            for route in discovery_routes()
        }
    return _ROUTES_BY_KEY


def cluster_members(cluster_id: str) -> tuple[tuple[int, int], ...]:
    """功能簇成员（definitionId, graphKind），以 discovery/clusters/<id>.json 为准。

    routes.json 的 clusters[] 只记录每个变体的**原生**功能簇归属；跨簇 recipe 簇
    （discovery/index.json 里 crossClusterRecipe=true 的 farming）在 routes.json 里为空，
    只用 routes.json 会让 `cluster farming` 返回 0 个节点，与 discovery 记录的 count 矛盾。
    因此成员来源优先 clusters/<id>.json；文件缺失时才退回 routes.json 的 clusters[]。
    """

    if cluster_id not in _CLUSTER_MEMBERS_CACHE:
        pairs: set[tuple[int, int]] = set()
        path = discovery_dir() / "clusters" / f"{cluster_id}.json"
        if path.is_file():
            data = load_json(path)
            pairs = {
                (int(node["definitionId"]), int(node["graphKind"]))
                for node in data.get("nodes") or []
            }
        else:
            pairs = {
                (int(route["definitionId"]), int(route["graphKind"]))
                for route in discovery_routes()
                if cluster_id in [str(c) for c in route.get("clusters") or []]
            }
        _CLUSTER_MEMBERS_CACHE[cluster_id] = tuple(sorted(pairs))
    return _CLUSTER_MEMBERS_CACHE[cluster_id]


def clusters_by_variant() -> dict[tuple[int, int], list[str]]:
    """每个 (definitionId, graphKind) 归属的功能簇 id 列表（按 discovery/clusters/*.json）。"""

    global _CLUSTERS_BY_VARIANT
    if _CLUSTERS_BY_VARIANT is None:
        mapping: dict[tuple[int, int], set[str]] = {}
        for cluster in discovery_index()["clusters"]:
            cluster_id = str(cluster["id"])
            for pair in cluster_members(cluster_id):
                mapping.setdefault(pair, set()).add(cluster_id)
        _CLUSTERS_BY_VARIANT = {pair: sorted(ids) for pair, ids in mapping.items()}
    return _CLUSTERS_BY_VARIANT


def definitions_by_id() -> dict[int, dict[str, Any]]:
    return {int(item["definitionId"]): item for item in manifest_index()["definitions"]}


def shard_entry(shard_rel: str, definition_id: int) -> dict[str, Any]:
    if shard_rel not in _SHARD_ENTRY_CACHE:
        data = load_json(shard_path(shard_rel))
        _SHARD_ENTRY_CACHE[shard_rel] = {
            int(entry["definition"]["definitionId"]): entry
            for entry in data["definitions"]
        }
    entry = _SHARD_ENTRY_CACHE[shard_rel].get(definition_id)
    if entry is None:
        raise CliError(
            "DATA_INTEGRITY",
            f"manifest 不一致：index.json 把 definitionId={definition_id} 指向 "
            f"{shard_rel}，但该 shard 中没有这条定义。",
            EXIT_INTERNAL,
            {"definitionId": definition_id, "shard": shard_rel},
        )
    return entry


def known_graph_kinds() -> list[int]:
    return sorted(int(kind) for kind in manifest_index()["graphKinds"])


def require_graph_kind(graph_kind: int) -> int:
    known = known_graph_kinds()
    if graph_kind not in known:
        raise CliError(
            "GRAPH_KIND_NOT_FOUND",
            f"未知 graphKind={graph_kind}；manifest 记录的 graphKind 为 {known}"
            "（见 data/m2/node-capability/manifest/index.json 的 graphKinds）。",
            EXIT_NOT_FOUND,
            {"graphKind": graph_kind, "knownGraphKinds": known},
            hint="运行 version 可查看各 graphKind 的变体计数。",
        )
    return graph_kind


def definition_or_error(definition_id: int) -> dict[str, Any]:
    definitions = definitions_by_id()
    found = definitions.get(definition_id)
    if found is None:
        ids = definitions.keys()
        raise CliError(
            "NODE_NOT_FOUND",
            f"未找到 definitionId={definition_id} 的定义；manifest 记录 "
            f"{len(ids)} 个定义（definitionId 范围 {min(ids)}..{max(ids)}）。",
            EXIT_NOT_FOUND,
            {"definitionId": definition_id},
            hint="可运行 search --query <中文关键词> 或 version 先确认查询键。",
        )
    return found


def lookup_variant(
    definition_id: int, graph_kind: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """返回 (index 定义项, shard 定义条目, 该 graphKind 的变体记录)。"""
    gk = require_graph_kind(graph_kind)
    definition = definition_or_error(definition_id)
    entry = shard_entry(str(definition["shard"]), definition_id)
    variants = entry["variants"]
    for variant in variants:
        if int(variant["graphKind"]) == gk:
            return definition, entry, variant
    available = sorted(int(variant["graphKind"]) for variant in variants)
    raise CliError(
        "VARIANT_NOT_FOUND",
        f"definitionId={definition_id}（{definition['name']}）存在，但没有 "
        f"graphKind={gk} 的变体；该定义可用 graphKind={available}。",
        EXIT_NOT_FOUND,
        {"definitionId": definition_id, "graphKind": gk, "availableGraphKinds": available},
        hint="同一 definitionId 可能只在其它 graphKind 下记录（见 version 的 graphKinds）。",
    )


def checked_limit(value: int, maximum: int, flag: str = "--limit") -> int:
    if value < 1 or value > maximum:
        raise CliError(
            "ARGUMENT_ERROR",
            f"{flag} 必须在 1..{maximum} 之间，收到 {value}。",
            EXIT_ARGUMENT,
            {"limit": value},
        )
    return value


# ---------------------------------------------------------------------------
# 能力记录构造
# ---------------------------------------------------------------------------


def build_capability_record(
    definition: dict[str, Any], entry: dict[str, Any], variant: dict[str, Any]
) -> dict[str, Any]:
    defn = entry["definition"]
    official = defn.get("officialFunction") or {}
    official_entries = official.get("entries") or []
    return {
        "definitionId": int(defn["definitionId"]),
        "graphKind": int(variant["graphKind"]),
        "stableKey": variant["stableKey"],
        "side": variant["side"],
        "name": variant["name"],
        "family": defn["family"],
        "category": variant["category"],
        "contractId": variant["contractId"],
        "grade": {
            "level": variant["grade"]["level"],
            "reason": variant["grade"]["reason"],
        },
        "runtimeVerified": bool(variant["runtimeVerified"]),
        "evidenceRefs": variant["evidenceRefs"],
        "ports": variant["ports"],
        "portCount": int(variant["portCount"]),
        "hasDynamicPorts": bool(variant["hasDynamicPorts"]),
        "dynamicPorts": variant["dynamicPorts"],
        "recipe": variant["recipe"],
        "menuPaths": variant["menuPaths"],
        "availableInMenus": variant["availableInMenus"],
        "listedInMenus": bool(variant["listedInMenus"]),
        "menuVisibility": variant["menuVisibility"],
        "definition": {
            "definitionId": int(defn["definitionId"]),
            "name": defn["name"],
            "family": defn["family"],
            "resource": defn["resource"],
            "resourceNetworkId": defn["resourceNetworkId"],
            "graphKinds": defn["graphKinds"],
            "sides": defn["sides"],
            "officialFunction": {
                "present": bool(official.get("present")),
                "entryCount": len(official_entries),
            },
            "runtimeVerified": bool(defn.get("runtimeVerified", False)),
            "unknowns": defn.get("unknowns", []),
        },
        "source": {
            "manifest": rel_path(manifest_dir() / "index.json"),
            "shard": rel_path(shard_path(str(definition["shard"]))),
        },
    }


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_query(args: argparse.Namespace) -> int:
    definition, entry, variant = lookup_variant(args.definition_id, args.graph_kind)
    return success(
        "query",
        query={"definitionId": args.definition_id, "graphKind": args.graph_kind},
        record=build_capability_record(definition, entry, variant),
    )


def cmd_ports(args: argparse.Namespace) -> int:
    _definition, _entry, variant = lookup_variant(args.definition_id, args.graph_kind)
    return success(
        "ports",
        query={"definitionId": args.definition_id, "graphKind": args.graph_kind},
        definitionId=args.definition_id,
        graphKind=args.graph_kind,
        name=variant["name"],
        stableKey=variant["stableKey"],
        side=variant["side"],
        portCount=int(variant["portCount"]),
        ports=variant["ports"],
    )


def _search_rank(reasons: set[str]) -> int:
    if "definition.name" in reasons or "definition.family" in reasons:
        return 0
    if "nativeLeaf" in reasons:
        return 1
    return 2


def cmd_search(args: argparse.Namespace) -> int:
    keyword = args.query.strip()
    if not keyword:
        raise CliError(
            "ARGUMENT_ERROR",
            "--query 不能为空字符串；请给出中文关键词，例如 字典、商店、选项卡。",
            EXIT_ARGUMENT,
            {"query": args.query},
        )
    limit = checked_limit(args.limit, MAX_SEARCH_LIMIT)
    graph_kind = None if args.graph_kind is None else require_graph_kind(args.graph_kind)
    needle = keyword.casefold()

    matched: dict[tuple[int, int], set[str]] = {}

    def add(definition_id: int, kind: int, reason: str) -> None:
        if graph_kind is not None and kind != graph_kind:
            return
        matched.setdefault((definition_id, kind), set()).add(reason)

    definitions = manifest_index()["definitions"]
    for definition in definitions:
        definition_id = int(definition["definitionId"])
        if needle in str(definition["name"]).casefold():
            for variant in definition["variants"]:
                add(definition_id, int(variant["graphKind"]), "definition.name")
        if needle in str(definition.get("family", "")).casefold():
            for variant in definition["variants"]:
                add(definition_id, int(variant["graphKind"]), "definition.family")

    matched_clusters: dict[str, dict[str, Any]] = {}
    for cluster in discovery_index()["clusters"]:
        hit = needle in str(cluster["name"]).casefold() or any(
            needle in str(alias).casefold() for alias in cluster.get("aliases", [])
        )
        if hit:
            matched_clusters[str(cluster["id"])] = cluster

    # 簇名/别名命中后展开簇成员（含跨簇 recipe 簇 farming），成员口径与 cluster 子命令一致。
    for cluster_id in sorted(matched_clusters):
        for member_definition_id, member_kind in cluster_members(cluster_id):
            add(member_definition_id, member_kind, f"cluster:{cluster_id}")

    for route in discovery_routes():
        definition_id = int(route["definitionId"])
        kind = int(route["graphKind"])
        if any(needle in str(leaf).casefold() for leaf in route.get("nativeLeaves", [])):
            add(definition_id, kind, "nativeLeaf")

    definitions_by_id_ = definitions_by_id()
    routes = routes_by_key()
    clusters_of_variant = clusters_by_variant()
    hits: list[dict[str, Any]] = []
    for (definition_id, kind), reasons in matched.items():
        definition = definitions_by_id_.get(definition_id)
        if definition is None:
            continue
        variant = next(
            (v for v in definition["variants"] if int(v["graphKind"]) == kind), None
        )
        if variant is None:
            continue
        route = routes.get((definition_id, kind), {})
        hit_clusters = clusters_of_variant.get((definition_id, kind)) or [
            str(c) for c in route.get("clusters") or []
        ]
        hits.append(
            {
                "definitionId": definition_id,
                "graphKind": kind,
                "stableKey": variant["stableKey"],
                "name": definition["name"],
                "family": definition["family"],
                "side": variant["side"],
                "portCount": int(variant["portCount"]),
                "grade": {"level": variant["grade"]},
                "clusters": sorted(hit_clusters),
                "nativeLeaves": sorted(str(leaf) for leaf in route.get("nativeLeaves", [])),
                "menuVisibility": route.get("menuVisibility"),
                "match": sorted(reasons),
            }
        )

    hits.sort(key=lambda hit: (_search_rank(set(hit["match"])), hit["definitionId"], hit["graphKind"]))
    total = len(hits)
    if total == 0:
        raise CliError(
            "SEARCH_NO_MATCH",
            f"关键词 {keyword!r} 未命中任何节点名称 / 功能簇名称或别名 / 原生菜单叶子"
            f"（graphKind={graph_kind if graph_kind is not None else '任意'}）。",
            EXIT_NOT_FOUND,
            {"query": keyword, "graphKind": graph_kind},
            extra={"total": 0, "results": []},
            hint="尝试更短的中文关键词（例如 字典、商店），或运行 cluster <簇id> 浏览功能簇。",
        )
    return success(
        "search",
        query={"query": keyword, "graphKind": graph_kind, "limit": limit},
        total=total,
        results=hits[:limit],
    )


def _enum_table(table: dict[str, Any], match: list[str]) -> dict[str, Any]:
    options = table.get("options") or []
    return {
        "id": int(table["id"]),
        "name": table["name"],
        "optionCount": len(options),
        "options": options,
        "match": sorted(match),
    }


def cmd_enums(args: argparse.Namespace) -> int:
    if args.enum_id is None and args.query is None:
        raise CliError(
            "ARGUMENT_ERROR",
            "enums 需要 --enum-id <ID> 或 --query <文本> 之一。",
            EXIT_ARGUMENT,
            {"enumId": None, "query": None},
            hint="例如：enums --enum-id 1；或 enums --query 比较 --limit 10。",
        )
    if args.enum_id is not None and args.query is not None:
        raise CliError(
            "ARGUMENT_ERROR",
            "--enum-id 与 --query 不能同时使用；精确取表用 --enum-id，检索用 --query。",
            EXIT_ARGUMENT,
            {"enumId": args.enum_id, "query": args.query},
        )
    limit = checked_limit(args.limit, MAX_ENUM_LIMIT)
    tables = enums_data()["tables"]

    if args.enum_id is not None:
        table = tables.get(str(args.enum_id))
        if table is None:
            ids = sorted(int(key) for key in tables)
            raise CliError(
                "ENUM_NOT_FOUND",
                f"未找到 enumId={args.enum_id} 的枚举表；enums.json 记录 "
                f"{len(ids)} 张表（id 范围 {ids[0]}..{ids[-1]}）。",
                EXIT_NOT_FOUND,
                {"enumId": args.enum_id},
                hint="可运行 enums --query <中文名> 按表名或选项名检索。",
            )
        return success(
            "enums",
            query={"enumId": args.enum_id},
            total=1,
            tables=[_enum_table(table, ["id"])],
        )

    keyword = str(args.query).strip()
    if not keyword:
        raise CliError(
            "ARGUMENT_ERROR",
            "--query 不能为空字符串；请给出枚举表名或选项名的中文关键词。",
            EXIT_ARGUMENT,
            {"query": args.query},
        )
    needle = keyword.casefold()
    found: list[tuple[int, dict[str, Any]]] = []
    for table_id, table in tables.items():
        reasons: list[str] = []
        if needle in str(table["name"]).casefold():
            reasons.append("name")
        if any(needle in str(option["name"]).casefold() for option in table.get("options", [])):
            reasons.append("option")
        if reasons:
            found.append((int(table_id), _enum_table(table, reasons)))
    found.sort(key=lambda item: item[0])
    total = len(found)
    if total == 0:
        raise CliError(
            "ENUM_NOT_FOUND",
            f"枚举检索 {keyword!r} 未命中任何表名或选项名；enums.json 共 {len(tables)} 张表。",
            EXIT_NOT_FOUND,
            {"query": keyword},
            extra={"total": 0, "tables": []},
            hint="尝试更短的关键词（例如 比较、布尔），或用 --enum-id 精确取表。",
        )
    return success(
        "enums",
        query={"query": keyword, "limit": limit},
        total=total,
        tables=[table for _table_id, table in found[:limit]],
    )


def _cluster_node(definition_id: int, kind: int, cluster_id: str) -> dict[str, Any]:
    definition = definitions_by_id().get(definition_id)
    if definition is None:
        raise CliError(
            "DATA_INTEGRITY",
            f"discovery 功能簇 {cluster_id!r} 与 manifest 不一致：definitionId={definition_id} "
            "在 index.json 中不存在。",
            EXIT_INTERNAL,
            {"definitionId": definition_id, "graphKind": kind, "cluster": cluster_id},
        )
    entry = shard_entry(str(definition["shard"]), definition_id)
    variant = next((v for v in entry["variants"] if int(v["graphKind"]) == kind), None)
    if variant is None:
        raise CliError(
            "DATA_INTEGRITY",
            f"discovery 功能簇 {cluster_id!r} 与 manifest 不一致：definitionId={definition_id} "
            f"没有 graphKind={kind} 的变体记录。",
            EXIT_INTERNAL,
            {"definitionId": definition_id, "graphKind": kind, "cluster": cluster_id},
        )
    route = routes_by_key().get((definition_id, kind), {})
    clusters = clusters_by_variant().get((definition_id, kind))
    if not clusters:
        clusters = sorted({cluster_id} | {str(c) for c in route.get("clusters") or []})
    return {
        "definitionId": definition_id,
        "graphKind": kind,
        "stableKey": variant["stableKey"],
        "name": variant["name"],
        "family": definition["family"],
        "side": variant["side"],
        "grade": variant["grade"],
        "portCount": int(variant["portCount"]),
        "hasDynamicPorts": bool(variant["hasDynamicPorts"]),
        "menuPaths": variant["menuPaths"],
        "listedInMenus": bool(variant["listedInMenus"]),
        "menuVisibility": variant["menuVisibility"],
        "clusters": sorted(str(c) for c in clusters),
        "nativeLeaves": sorted(str(leaf) for leaf in route.get("nativeLeaves", [])),
    }


def cmd_cluster(args: argparse.Namespace) -> int:
    raw = args.cluster.strip()
    if not raw:
        raise CliError(
            "ARGUMENT_ERROR",
            "cluster 需要功能簇 id（例如 shop）；不能为空。",
            EXIT_ARGUMENT,
            {"cluster": args.cluster},
        )
    clusters = discovery_index()["clusters"]
    by_id = {str(cluster["id"]): cluster for cluster in clusters}
    cluster = by_id.get(raw)
    if cluster is None:
        cluster = next((c for c in clusters if str(c["name"]) == raw), None)
    if cluster is None:
        known = sorted(by_id)
        raise CliError(
            "CLUSTER_NOT_FOUND",
            f"未找到功能簇 {raw!r}；discovery/index.json 记录 {len(known)} 个功能簇 id：{known}。",
            EXIT_NOT_FOUND,
            {"cluster": raw},
            hint="cluster 接受功能簇 id（如 shop）或完整中文名。",
        )

    graph_kind = None if args.graph_kind is None else require_graph_kind(args.graph_kind)
    limit = checked_limit(args.limit, MAX_CLUSTER_LIMIT)
    cluster_id = str(cluster["id"])
    members = list(cluster_members(cluster_id))
    declared = cluster.get("count")
    if isinstance(declared, int) and declared > 0 and not members:
        # 防御：discovery 说这个簇有节点、但成员口径算出 0，绝不能静默返回 total:0。
        raise CliError(
            "DATA_INTEGRITY",
            f"功能簇 {cluster_id!r} 在 discovery/index.json 记为 {declared} 个节点，但 "
            f"discovery/clusters/{cluster_id}.json 为空或缺少 nodes[]；拒绝返回 0 个节点。",
            EXIT_INTERNAL,
            {"cluster": cluster_id, "declaredCount": declared},
            hint="核对 discovery/clusters/ 下的簇页，或先重建 discovery 索引。",
        )
    if graph_kind is not None:
        members = [pair for pair in members if pair[1] == graph_kind]
    members.sort()

    nodes = [_cluster_node(definition_id, kind, cluster_id) for definition_id, kind in members]
    return success(
        "cluster",
        query={
            "cluster": raw,
            "clusterId": cluster_id,
            "graphKind": graph_kind,
            "limit": limit,
        },
        cluster={
            "id": cluster_id,
            "name": cluster["name"],
            "purpose": cluster.get("purpose"),
            "aliases": cluster.get("aliases", []),
            "count": cluster.get("count"),
            "byFamily": cluster.get("byFamily", {}),
            "byGraphKind": cluster.get("byGraphKind", {}),
            "runtimeVerified": bool(cluster.get("runtimeVerified", False)),
        },
        total=len(nodes),
        nodes=nodes[:limit],
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_version(_args: argparse.Namespace) -> int:
    index = manifest_index()
    enums = enums_data()
    discovery = discovery_index()
    routes = discovery_routes()

    definitions = index["definitions"]
    counts = {
        "definitions": len(definitions),
        "variants": sum(len(item["variants"]) for item in definitions),
        "ports": sum(
            int(variant["portCount"])
            for item in definitions
            for variant in item["variants"]
        ),
        "enumGroups": len(enums["tables"]),
        "shards": len(index.get("artifacts", {}).get("shards", [])),
    }

    checks: list[dict[str, Any]] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append(
            {"name": name, "ok": expected == actual, "expected": expected, "actual": actual}
        )

    declared = index.get("counts", {})
    for key in ("definitions", "variants", "ports", "enumGroups", "shards"):
        check(f"counts.{key}", int(declared.get(key, -1)), counts[key])
    check("enums.count", int(enums.get("count", -1)), len(enums["tables"]))

    manifest_root = manifest_dir()
    source_hashes: dict[str, Any] = {
        "manifestIndex": file_sha256(manifest_root / "index.json"),
        "manifestEnums": file_sha256(manifest_root / "enums.json"),
        "discoveryIndex": file_sha256(discovery_dir() / "index.json"),
        "discoveryRoutes": file_sha256(discovery_dir() / "routes.json"),
        "shards": {},
    }
    check(
        "sha256:enums.json",
        index.get("artifacts", {}).get("enums", {}).get("sha256"),
        source_hashes["manifestEnums"],
    )
    check(
        "sha256:discovery/index.json",
        index.get("sourceHashes", {}).get("discoveryIndex"),
        source_hashes["discoveryIndex"],
    )
    for shard in index.get("artifacts", {}).get("shards", []):
        shard_rel = str(shard["path"])
        actual = file_sha256(manifest_root / shard_rel)
        source_hashes["shards"][shard_rel.split("/")[-1]] = actual
        check(f"sha256:{shard_rel}", shard.get("sha256"), actual)

    source_hashes["recordedUpstream"] = index.get("sourceHashes", {})
    integrity_ok = all(item["ok"] for item in checks)
    if not integrity_ok:
        failed = [item["name"] for item in checks if not item["ok"]]
        raise CliError(
            "DATA_INTEGRITY",
            f"manifest 完整性检查失败：{failed}；数据可能被修改或未完整构建。",
            EXIT_INTERNAL,
            {},
            extra={"integrity": {"ok": False, "checks": checks}},
        )

    graph_kinds = {
        str(kind): int(count)
        for kind, count in sorted(
            index.get("graphKinds", {}).items(), key=lambda item: int(item[0])
        )
    }
    return success(
        "version",
        artifact="node-capability-api",
        dataArtifact=index.get("artifact"),
        commands=list(COMMANDS),
        counts=counts,
        graphKinds=graph_kinds,
        observedUtc=index.get("observedUtc"),
        sourceHashes=source_hashes,
        integrity={"ok": True, "checks": checks},
        runtimeVerified=False,
        exitCodes={
            "ok": EXIT_OK,
            "notFound": EXIT_NOT_FOUND,
            "argumentError": EXIT_ARGUMENT,
        },
        inputs={
            "manifest": MANIFEST_REL.as_posix(),
            "discovery": DISCOVERY_REL.as_posix(),
        },
    )


# ---------------------------------------------------------------------------
# graph-built：L3 真机图建成级证据（SPEC v1.2 §10）
# ---------------------------------------------------------------------------

_GRAPH_BUILT_CACHE: dict[str, Any] | None = None

#: 子类按证据强度排序；api 只输出子类，禁止把 EDITED 说成 BUILT。
GRAPH_BUILT_KIND_ORDER = (
    "L3-LIVE-GRAPH-BUILT",
    "L3-LIVE-GRAPH-BUILT-BRIDGE",
    "L3-LIVE-GRAPH-EDITED",
    "L3-BIND-READBACK",
)


def graph_built_path() -> Path:
    return repo_root() / GRAPH_BUILT_REL


def graph_built_index() -> dict[str, Any]:
    global _GRAPH_BUILT_CACHE
    if _GRAPH_BUILT_CACHE is None:
        path = graph_built_path()
        if not path.is_file():
            raise CliError(
                "DATA_NOT_FOUND",
                f"真机图建成级证据索引不存在：{rel_path(path)}；"
                "请先运行 tools/m2/node-capability/evidence/build.py。",
                EXIT_INTERNAL,
                {"path": rel_path(path)},
            )
        _GRAPH_BUILT_CACHE = load_json(path)
    return _GRAPH_BUILT_CACHE


def graph_built_source_sha() -> str:
    return file_sha256(graph_built_path())


def _graph_built_record(entry: dict[str, Any]) -> dict[str, Any]:
    """规整单条记录：字段稳定、顺序无关（json sort_keys 输出）。"""

    record = {
        "definitionId": int(entry["definitionId"]),
        "level": entry.get("level"),
        "kind": entry.get("kind"),
        "kindLabel": entry.get("kindLabel", ""),
        "graphIds": entry.get("graphIds")
        or ([entry["graphId"]] if entry.get("graphId") is not None else []),
        "graphNames": entry.get("graphNames")
        or ([entry["graphName"]] if entry.get("graphName") else []),
        "definitionNodeIds": entry.get("definitionNodeIds") or [],
        "sources": [
            {"path": source.get("path"), "sha256": source.get("sha256"), "role": source.get("role", "")}
            for source in entry.get("sources") or []
        ],
        "observedAtUtc": entry.get("observedAtUtc"),
        "evidenceRefs": entry.get("evidenceRefs") or [],
        "runtimeVerified": bool(entry.get("runtimeVerified", False)),
        "note": entry.get("note", ""),
    }
    return record


def _graph_built_records(index: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    definitions = index.get("definitions") or {}
    for key in sorted(definitions, key=lambda value: int(value)):
        for entry in definitions[key]:
            records.append(_graph_built_record(entry))
    return records


def cmd_graph_built(args: argparse.Namespace) -> int:
    """按 definitionId 查 L3 真机图建成级证据（--list 全量）。

    只读 evidence/graph-built-index.json；不改任何输入，不声明运行语义（L4）。
    """

    index = graph_built_index()
    counts = index.get("counts") or {}
    source_sha = graph_built_source_sha()
    negatives = index.get("negatives") or []
    if getattr(args, "list_all", False):
        records = _graph_built_records(index)
        return success(
            "graph-built",
            mode="list",
            indexSha256=source_sha,
            counts=counts,
            records=records,
            count=len(records),
            negatives=negatives,
        )
    definition_id = args.definition_id
    raw = (index.get("definitions") or {}).get(str(definition_id)) or []
    if not raw:
        raise CliError(
            "GRAPH_BUILT_NOT_FOUND",
            f"definitionId={definition_id} 没有真机图建成级证据记录"
            f"（索引只覆盖 {counts.get('definitions')} 个定义；其余定义最高 L2/L3-BIND-READBACK）。",
            EXIT_NOT_FOUND,
            {"definitionId": definition_id},
        )
    records = [_graph_built_record(entry) for entry in raw]
    return success(
        "graph-built",
        mode="definition",
        query={"definitionId": definition_id},
        indexSha256=source_sha,
        counts=counts,
        records=records,
        count=len(records),
        negatives=negatives,
    )


# ---------------------------------------------------------------------------
# argparse：参数错误也必须走 stdout JSON + 退出码 3
# ---------------------------------------------------------------------------


def positive_int(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"需要整数，收到 {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"需要正整数（>=1），收到 {value}")
    return value


class JsonArgumentParser(argparse.ArgumentParser):
    """argparse 默认往 stderr 打 usage 并 exit 2；这里改成抛 CliError（exit 3）。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise CliError("ARGUMENT_ERROR", message, EXIT_ARGUMENT)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="cli.py",
        description=(
            "node-capability-api：稳定 JSON 查询入口"
            "（query/search/ports/enums/cluster/version/graph-built）。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "退出码：0 命中；2 未找到（stdout 仍为 JSON 错误体）；3 参数错误。\n"
            "示例：\n"
            "  python -X utf8 -B tools/m2/node-capability/api/cli.py query --definition-id 307 --graph-kind 20000\n"
            "  python -X utf8 -B tools/m2/node-capability/api/cli.py search --query 字典 --limit 10\n"
            "  python -X utf8 -B tools/m2/node-capability/api/cli.py graph-built --definition-id 307\n"
            "  python -X utf8 -B tools/m2/node-capability/api/cli.py graph-built --list\n"
            "  python -X utf8 -B tools/m2/node-capability/api/cli.py version\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    query = subparsers.add_parser(
        "query", help="按 definitionId+graphKind 精确取能力记录（grade/ports/recipe/menuPaths）"
    )
    query.add_argument("--definition-id", type=positive_int, required=True, metavar="ID")
    query.add_argument("--graph-kind", type=positive_int, required=True, metavar="GK")
    query.set_defaults(handler=cmd_query)

    search = subparsers.add_parser(
        "search", help="按中文关键词检索节点（名称/功能簇名或别名/原生菜单叶子）"
    )
    search.add_argument("--query", type=str, required=True, metavar="TEXT")
    search.add_argument("--graph-kind", type=positive_int, default=None, metavar="GK")
    search.add_argument("--limit", type=positive_int, default=20, metavar="N")
    search.set_defaults(handler=cmd_search)

    ports = subparsers.add_parser("ports", help="按 definitionId+graphKind 取端口表")
    ports.add_argument("--definition-id", type=positive_int, required=True, metavar="ID")
    ports.add_argument("--graph-kind", type=positive_int, required=True, metavar="GK")
    ports.set_defaults(handler=cmd_ports)

    enums = subparsers.add_parser("enums", help="按 enumId 或中文关键词取枚举表与真实选项")
    enums.add_argument("--enum-id", type=positive_int, default=None, metavar="ID")
    enums.add_argument("--query", type=str, default=None, metavar="TEXT")
    enums.add_argument("--limit", type=positive_int, default=10, metavar="N")
    enums.set_defaults(handler=cmd_enums)

    cluster = subparsers.add_parser("cluster", help="按功能簇 id 列出簇内节点")
    cluster.add_argument("cluster", type=str, metavar="CLUSTER")
    cluster.add_argument("--graph-kind", type=positive_int, default=None, metavar="GK")
    cluster.add_argument("--limit", type=positive_int, default=MAX_CLUSTER_LIMIT, metavar="N")
    cluster.set_defaults(handler=cmd_cluster)

    version = subparsers.add_parser("version", help="输出来源 sha256 与 810/929/4637/103 计数")
    version.set_defaults(handler=cmd_version)

    graph_built = subparsers.add_parser(
        "graph-built",
        help="按 definitionId 查 L3 真机图建成级证据（子类 BUILT/BRIDGE/EDITED；--list 全量）",
    )
    graph_built_group = graph_built.add_mutually_exclusive_group(required=True)
    graph_built_group.add_argument("--definition-id", type=positive_int, metavar="ID")
    graph_built_group.add_argument("--list", action="store_true", dest="list_all")
    graph_built.set_defaults(handler=cmd_graph_built)

    return parser


def detect_command(argv: list[str]) -> str | None:
    for token in argv:
        if token in COMMANDS:
            return token
    return None


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv[:1] == ["--help"] or raw_argv[:1] == ["-h"]:
        build_parser().print_help()
        return EXIT_OK
    try:
        args = build_parser().parse_args(raw_argv)
    except CliError as exc:
        exc.command = exc.command or detect_command(raw_argv)
        if not exc.query:
            exc.query = {"argv": raw_argv}
        if exc.hint is None:
            exc.hint = "运行 python -X utf8 -B tools/m2/node-capability/api/cli.py --help 查看用法。"
        return fail(exc)

    handler = getattr(args, "handler", None)
    if handler is None:  # pragma: no cover - argparse 已保证
        return fail(
            CliError(
                "ARGUMENT_ERROR",
                "缺少子命令；可用 query/search/ports/enums/cluster/version。",
                EXIT_ARGUMENT,
                {"argv": raw_argv},
                command=None,
            )
        )
    try:
        return handler(args)
    except CliError as exc:
        exc.command = exc.command or getattr(args, "command", None)
        return fail(exc)
    except BrokenPipeError:  # pragma: no cover - 下游提前关闭管道
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001 - 把意外错误也变成稳定 JSON
        return fail(
            CliError(
                "INTERNAL_ERROR",
                f"{type(exc).__name__}: {exc}",
                EXIT_INTERNAL,
                command=getattr(args, "command", None),
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
