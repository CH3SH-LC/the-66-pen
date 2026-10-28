#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""node-capability-api 断言自检（D4）。

真跑 cli.py 的六个子命令，校验：
  * 307 / 702 / 1 / 1088 已知能力记录的关键字段（grade/ports/recipe/menuPaths）；
  * 枚举表 1 / 2 的真实选项非空；中文关键词 字典 / 商店 有命中；
  * 未知 definitionId=999999 / enum / 簇 的退出码 2 且 stdout 仍是 JSON 错误体；
  * version 的 810 / 929 / 4637 / 103 计数与来源 sha256；
  * 参数错误退出码 3；输出逐字节确定性；schema.json 结构（可选 Draft 2020-12 校验）。
* v2（2026-10-19）：新增 graph-built 子命令断言（子类不得混称、source sha256 可重算、EDITED≠BUILT）。

任一断言失败 -> 退出码 1。全部通过 -> 退出码 0。
不写 wall-clock、不用随机数；结果文件只含确定性字段。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLI = HERE / "cli.py"
SCHEMA = HERE / "schema.json"

PORT_KEYS = {
    "index",
    "kind",
    "direction",
    "name",
    "typeCode",
    "typeName",
    "genericId",
    "serverParamType",
    "enumGroupId",
}
COMMANDS = ("query", "search", "ports", "enums", "cluster", "version", "graph-built")

VALIDATOR = None
VALIDATOR_IMPORT_ERROR = ""
try:  # 可选依赖：没有 jsonschema 时仍执行全部业务断言
    import jsonschema
    from jsonschema import Draft202012Validator
except Exception as exc:  # noqa: BLE001
    VALIDATOR_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    try:
        _schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        VALIDATOR = Draft202012Validator(_schema)
    except Exception as exc:  # noqa: BLE001
        VALIDATOR_IMPORT_ERROR = f"schema 加载失败: {type(exc).__name__}: {exc}"


def find_root() -> Path:
    for base in (HERE, *HERE.parents):
        if (base / "data/m2/node-capability/manifest/index.json").is_file():
            return base
    raise SystemExit("FATAL 找不到仓库根（data/m2/node-capability/manifest/index.json 不存在）")


ROOT = find_root()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def invoke(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(CLI), *args],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return (
        int(completed.returncode),
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def single_json_line(text: str) -> bool:
    return text.endswith("\n") and text.count("\n") == 1


_CLI_MODULE: Any = None


def load_cli_module(checker: "Checker") -> Any:
    """进程内加载同一个 cli.py（用于跨来源一致性与全量 schema 断言）。

    只做 import，不替换任何行为；加载失败记一条 cli.module-load 断言并返回 None。
    """

    global _CLI_MODULE
    if _CLI_MODULE is not None:
        return _CLI_MODULE
    spec = importlib.util.spec_from_file_location("node_capability_api_cli_for_check", CLI)
    if spec is None or spec.loader is None:  # pragma: no cover
        checker.check("cli.module-load", False, "无法为 cli.py 建立模块 spec")
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - 导入失败也是一条可报告的断言
        checker.check(
            "cli.module-load",
            False,
            f"加载 cli.py 模块失败: {type(exc).__name__}: {exc}",
        )
        return None
    _CLI_MODULE = module
    return module


class Checker:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.schema_validated = 0

    def check(self, name: str, condition: Any, detail: str = "") -> bool:
        ok = bool(condition)
        self.results.append({"name": name, "ok": ok, "detail": "" if ok else str(detail)})
        suffix = "" if ok else f" :: {detail}"
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")
        return ok

    def note(self, name: str, message: str) -> None:
        self.notes.append(f"{name}: {message}")
        print(f"NOTE {name}: {message}")

    def expect(
        self, label: str, args: list[str], exit_code: int
    ) -> tuple[dict[str, Any] | None, str]:
        code, out, err = invoke(args)
        try:
            data = json.loads(out) if out.strip() else None
        except json.JSONDecodeError:
            data = None
        self.check(
            f"{label}.exit",
            code == exit_code,
            f"expected exit {exit_code}, got {code}; stdout={out[:240]!r}; stderr={err[:240]!r}",
        )
        self.check(
            f"{label}.stderr-empty",
            err == "",
            f"stderr={err[:240]!r}",
        )
        self.check(
            f"{label}.stdout-json",
            data is not None and single_json_line(out),
            f"stdout={out[:240]!r}",
        )
        if data is not None:
            self.check(
                f"{label}.ok-flag",
                data.get("ok") is (exit_code == 0),
                f"expected ok={exit_code == 0}, got {data.get('ok')!r}",
            )
        return data, out

    def validate_schema(self, label: str, data: dict[str, Any] | None) -> None:
        if VALIDATOR is None:
            self.note(
                f"{label}.schema",
                f"jsonschema 不可用，跳过 Draft 2020-12 校验（{VALIDATOR_IMPORT_ERROR}）",
            )
            return
        if data is None:
            self.check(f"{label}.schema", False, "没有可校验的 JSON 对象")
            return
        errors = sorted(VALIDATOR.iter_errors(data), key=lambda error: list(error.path))
        self.schema_validated += 1
        self.check(
            f"{label}.schema",
            not errors,
            "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:3]),
        )

    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.results if not item["ok"]]


def run_version_checks(checker: Checker) -> None:
    data, out = checker.expect("version", ["version"], 0)
    if data is None:
        return
    counts = data.get("counts", {})
    checker.check(
        "version.counts",
        counts.get("definitions") == 810
        and counts.get("variants") == 929
        and counts.get("ports") == 4637
        and counts.get("enumGroups") == 103
        and counts.get("shards") == 8,
        f"counts={counts!r}",
    )
    checker.check(
        "version.graphKinds",
        data.get("graphKinds")
        == {"20000": 500, "20001": 122, "20002": 197, "20007": 110},
        f"graphKinds={data.get('graphKinds')!r}",
    )

    manifest_root = ROOT / "data/m2/node-capability/manifest"
    discovery_root = ROOT / "data/node-workbench/discovery"
    hashes = data.get("sourceHashes", {})
    actual = {
        "manifestIndex": sha256_file(manifest_root / "index.json"),
        "manifestEnums": sha256_file(manifest_root / "enums.json"),
        "discoveryIndex": sha256_file(discovery_root / "index.json"),
        "discoveryRoutes": sha256_file(discovery_root / "routes.json"),
    }
    checker.check(
        "version.sourceHashes",
        all(hashes.get(key) == value for key, value in actual.items()),
        f"reported={ {key: hashes.get(key) for key in actual} !r} actual={actual!r}",
    )

    manifest = json.loads((manifest_root / "index.json").read_text(encoding="utf-8"))
    expected_shards = {
        str(item["path"]).split("/")[-1]: sha256_file(manifest_root / str(item["path"]))
        for item in manifest.get("artifacts", {}).get("shards", [])
    }
    checker.check(
        "version.shardHashes",
        hashes.get("shards") == expected_shards,
        f"reported={hashes.get('shards')!r}",
    )
    upstream = hashes.get("recordedUpstream", {})
    checker.check(
        "version.recordedUpstream",
        set(upstream)
        == {"catalog", "summary", "recipes", "contractsIndex", "discoveryIndex"}
        and all(is_sha256(value) for value in upstream.values())
        and upstream.get("discoveryIndex") == actual["discoveryIndex"],
        f"recordedUpstream={upstream!r}",
    )

    integrity = data.get("integrity", {})
    checks = integrity.get("checks", [])
    checker.check(
        "version.integrity",
        integrity.get("ok") is True
        and len(checks) >= 14
        and all(item.get("ok") is True for item in checks),
        f"integrity={integrity!r}",
    )
    checker.check(
        "version.exitCodes",
        data.get("exitCodes") == {"ok": 0, "notFound": 2, "argumentError": 3},
        f"exitCodes={data.get('exitCodes')!r}",
    )
    checker.check(
        "version.no-wall-clock-fields",
        not any(
            token in out
            for token in ('"generatedAt"', '"timestamp"', '"checkedAt"', '"wallClock"')
        ),
        "输出里出现 wall-clock 字段",
    )
    checker.check(
        "version.observedUtc",
        isinstance(data.get("observedUtc"), str) and len(data["observedUtc"]) > 0,
        f"observedUtc={data.get('observedUtc')!r}",
    )

    code2, out2, err2 = invoke(["version"])
    checker.check(
        "version.deterministic",
        code2 == 0 and err2 == "" and out2 == out,
        f"second run exit={code2} stderr={err2[:120]!r} identical={out2 == out}",
    )
    checker.validate_schema("version", data)


def run_query_checks(checker: Checker) -> None:
    data, _out = checker.expect(
        "query307", ["query", "--definition-id", "307", "--graph-kind", "20000"], 0
    )
    if data is not None:
        record = data.get("record", {})
        checker.check(
            "query307.identity",
            record.get("definitionId") == 307
            and record.get("graphKind") == 20000
            and record.get("name") == "选项卡选中时"
            and record.get("family") == "事件节点"
            and record.get("side") == "server"
            and record.get("stableKey") == "10001:20000:22000:0:307",
            f"record identity fields wrong: { {k: record.get(k) for k in ('definitionId', 'graphKind', 'name', 'family', 'side', 'stableKey')} !r}",
        )
        grade = record.get("grade", {})
        checker.check(
            "query307.grade",
            grade.get("level") == "L2"
            and isinstance(grade.get("reason"), str)
            and len(grade["reason"]) > 0
            and record.get("runtimeVerified") is False,
            f"grade={grade!r} runtimeVerified={record.get('runtimeVerified')!r}",
        )
        ports = record.get("ports", [])
        checker.check(
            "query307.ports",
            record.get("portCount") == 6
            and len(ports) == 6
            and all(set(port) == PORT_KEYS for port in ports)
            and {"事件源实体", "选项卡序号", "选择者实体"} <= {port.get("name") for port in ports}
            and all(port.get("direction") in ("input", "output") for port in ports),
            f"portCount={record.get('portCount')!r} names={[port.get('name') for port in ports]!r}",
        )
        recipe = record.get("recipe", {})
        build_plan = recipe.get("buildPlanNode", {})
        checker.check(
            "query307.recipe",
            isinstance(recipe.get("nativeAddMethod"), str)
            and len(recipe.get("nativeAddMethod", "")) > 0
            and build_plan.get("definitionId") == 307
            and build_plan.get("x") == 0
            and build_plan.get("y") == 0,
            f"recipe={recipe!r}",
        )
        menu_paths = record.get("menuPaths", [])
        checker.check(
            "query307.menuPaths",
            len(menu_paths) >= 1
            and all({"path", "treeId"} == set(item) for item in menu_paths)
            and any(
                "选项卡" in segment
                for item in menu_paths
                for segment in item.get("path", [])
            ),
            f"menuPaths={menu_paths!r}",
        )
        resource = record.get("definition", {}).get("resource", {})
        checker.check(
            "query307.evidence-and-resource",
            len(record.get("evidenceRefs", [])) >= 1
            and is_sha256(resource.get("sha256"))
            and isinstance(resource.get("path"), str)
            and len(resource.get("path", "")) > 0,
            f"evidenceRefs={len(record.get('evidenceRefs', []))} resource={resource!r}",
        )
        checker.validate_schema("query307", data)

    # 702 打开商店：簇 shop 的核心节点，端口是 玩家实体 + 商店归属者实体 + 商店序号
    data, _out = checker.expect(
        "query702", ["query", "--definition-id", "702", "--graph-kind", "20000"], 0
    )
    if data is not None:
        record = data.get("record", {})
        ports = record.get("ports", [])
        checker.check(
            "query702.identity-and-ports",
            record.get("name") == "打开商店"
            and record.get("family") == "执行节点"
            and record.get("grade", {}).get("level") == "L2"
            and record.get("portCount") == 5
            and len(ports) == 5
            and {"玩家实体", "商店归属者实体", "商店序号"} <= {port.get("name") for port in ports},
            f"name={record.get('name')!r} portCount={record.get('portCount')!r} names={[port.get('name') for port in ports]!r}",
        )
        checker.check(
            "query702.menuPaths",
            any(
                "商店" in segment
                for item in record.get("menuPaths", [])
                for segment in item.get("path", [])
            ),
            f"menuPaths={record.get('menuPaths')!r}",
        )

    # 1 打印字符串：3 个端口，字符串参数 serverParamType=6
    data, _out = checker.expect(
        "query1", ["query", "--definition-id", "1", "--graph-kind", "20000"], 0
    )
    if data is not None:
        record = data.get("record", {})
        ports = record.get("ports", [])
        string_port = next((port for port in ports if port.get("name") == "字符串"), {})
        checker.check(
            "query1.ports-and-recipe",
            record.get("name") == "打印字符串"
            and record.get("portCount") == 3
            and len(ports) == 3
            and record.get("hasDynamicPorts") is False
            and string_port.get("serverParamType") == 6
            and string_port.get("genericId") == 6
            and record.get("grade", {}).get("level") == "L2",
            f"record={ {k: record.get(k) for k in ('name', 'portCount', 'hasDynamicPorts')} !r} stringPort={string_port!r}",
        )

    # 1088 建立字典：泛型字典端口（typeName=Generics）
    data, _out = checker.expect(
        "query1088", ["query", "--definition-id", "1088", "--graph-kind", "20000"], 0
    )
    if data is not None:
        record = data.get("record", {})
        ports = record.get("ports", [])
        dict_port = next((port for port in ports if port.get("name") == "字典"), {})
        checker.check(
            "query1088.ports",
            record.get("name") == "建立字典"
            and record.get("family") == "运算节点"
            and record.get("portCount") == 3
            and {"键列表", "值列表", "字典"} == {port.get("name") for port in ports}
            and dict_port.get("direction") == "output"
            and dict_port.get("typeName") == "Generics"
            and record.get("grade", {}).get("level") == "L2",
            f"name={record.get('name')!r} ports={ports!r}",
        )

    # 200038 播放限时特效：客户端变体，含 recording 方向未知的 kind=5 端口（direction=unknown）
    data, _out = checker.expect(
        "query200038", ["query", "--definition-id", "200038", "--graph-kind", "20002"], 0
    )
    if data is not None:
        record = data.get("record", {})
        ports = record.get("ports", [])
        checker.check(
            "query200038.unknown-direction",
            record.get("name") == "播放限时特效"
            and record.get("graphKind") == 20002
            and record.get("side") == "client"
            and record.get("portCount") == 9
            and len(ports) == 9
            and "unknown" in {port.get("direction") for port in ports},
            f"name={record.get('name')!r} portCount={record.get('portCount')!r} directions={[port.get('direction') for port in ports]!r}",
        )
        checker.validate_schema("query200038", data)

    # 未知 definitionId -> exit 2 + NODE_NOT_FOUND，stdout 仍是 JSON
    data, _out = checker.expect(
        "query-unknown", ["query", "--definition-id", "999999", "--graph-kind", "20000"], 2
    )
    if data is not None:
        error = data.get("error", {})
        checker.check(
            "query-unknown.error-body",
            error.get("code") == "NODE_NOT_FOUND"
            and "999999" in str(error.get("message", ""))
            and error.get("query", {}).get("definitionId") == 999999,
            f"error={error!r}",
        )
        checker.validate_schema("query-unknown", data)

    # 定义存在但 graphKind 不存在 -> VARIANT_NOT_FOUND（仍是 exit 2）
    data, _out = checker.expect(
        "query-variant-missing", ["query", "--definition-id", "1", "--graph-kind", "20007"], 2
    )
    if data is not None:
        error = data.get("error", {})
        checker.check(
            "query-variant-missing.error-body",
            error.get("code") == "VARIANT_NOT_FOUND"
            and "20007" in str(error.get("message", ""))
            and 20000 in error.get("query", {}).get("availableGraphKinds", []),
            f"error={error!r}",
        )

    # 未知 graphKind -> GRAPH_KIND_NOT_FOUND（仍是 exit 2）
    data, _out = checker.expect(
        "query-graphkind-unknown",
        ["query", "--definition-id", "1", "--graph-kind", "99999"],
        2,
    )
    if data is not None:
        error = data.get("error", {})
        checker.check(
            "query-graphkind-unknown.error-body",
            error.get("code") == "GRAPH_KIND_NOT_FOUND"
            and "99999" in str(error.get("message", "")),
            f"error={error!r}",
        )

    # 参数错误 -> exit 3
    data, _out = checker.expect("arg-missing-graphkind", ["query", "--definition-id", "1"], 3)
    if data is not None:
        error = data.get("error", {})
        checker.check(
            "arg-missing-graphkind.error-body",
            error.get("code") == "ARGUMENT_ERROR"
            and "--graph-kind" in str(error.get("message", "")),
            f"error={error!r}",
        )
    data, _out = checker.expect(
        "arg-bad-int",
        ["query", "--definition-id", "abc", "--graph-kind", "20000"],
        3,
    )
    if data is not None:
        checker.check(
            "arg-bad-int.error-body",
            data.get("error", {}).get("code") == "ARGUMENT_ERROR",
            f"error={data.get('error')!r}",
        )
    data, _out = checker.expect(
        "arg-bad-limit", ["search", "--query", "字典", "--limit", "0"], 3
    )
    if data is not None:
        checker.check(
            "arg-bad-limit.error-body",
            data.get("error", {}).get("code") == "ARGUMENT_ERROR",
            f"error={data.get('error')!r}",
        )
    data, _out = checker.expect("arg-enums-selector", ["enums"], 3)
    if data is not None:
        checker.check(
            "arg-enums-selector.error-body",
            data.get("error", {}).get("code") == "ARGUMENT_ERROR",
            f"error={data.get('error')!r}",
        )
    data, _out = checker.expect("arg-unknown-command", ["nosuch-command"], 3)
    if data is not None:
        checker.check(
            "arg-unknown-command.error-body",
            data.get("command") is None
            and data.get("error", {}).get("code") == "ARGUMENT_ERROR"
            and "invalid choice" in str(data.get("error", {}).get("message", "")),
            f"data={data!r}",
        )

    # 确定性：同一 query 两次逐字节一致
    code1, out1, _err1 = invoke(
        ["query", "--definition-id", "307", "--graph-kind", "20000"]
    )
    code2, out2, err2 = invoke(
        ["query", "--definition-id", "307", "--graph-kind", "20000"]
    )
    checker.check(
        "query307.deterministic",
        code1 == 0 and code2 == 0 and err2 == "" and out1 == out2,
        f"code1={code1} code2={code2} identical={out1 == out2}",
    )


def run_ports_checks(checker: Checker) -> None:
    data, _out = checker.expect(
        "ports1", ["ports", "--definition-id", "1", "--graph-kind", "20000"], 0
    )
    if data is not None:
        ports = data.get("ports", [])
        checker.check(
            "ports1.payload",
            data.get("definitionId") == 1
            and data.get("graphKind") == 20000
            and data.get("name") == "打印字符串"
            and data.get("portCount") == 3
            and len(ports) == 3
            and all(set(port) == PORT_KEYS for port in ports)
            and {port.get("direction") for port in ports} == {"input", "output"},
            f"payload={ {k: data.get(k) for k in ('definitionId', 'graphKind', 'name', 'portCount')} !r}",
        )
        checker.validate_schema("ports1", data)
    data, _out = checker.expect(
        "ports-unknown", ["ports", "--definition-id", "999999", "--graph-kind", "20000"], 2
    )
    if data is not None:
        checker.check(
            "ports-unknown.error-body",
            data.get("error", {}).get("code") == "NODE_NOT_FOUND"
            and "999999" in str(data.get("error", {}).get("message", "")),
            f"error={data.get('error')!r}",
        )


def run_enum_checks(checker: Checker) -> None:
    data, _out = checker.expect("enum1", ["enums", "--enum-id", "1"], 0)
    if data is not None:
        tables = data.get("tables", [])
        table = tables[0] if tables else {}
        options = table.get("options", [])
        checker.check(
            "enum1.real-options",
            data.get("total") == 1
            and len(tables) == 1
            and table.get("id") == 1
            and table.get("name") == "布尔值"
            and table.get("optionCount") == 2
            and len(options) == 2
            and {option.get("value") for option in options} == {0, 1}
            and all(option.get("name") for option in options),
            f"tables={tables!r}",
        )
        checker.validate_schema("enum1", data)

    data, _out = checker.expect("enum2", ["enums", "--enum-id", "2"], 0)
    if data is not None:
        tables = data.get("tables", [])
        table = tables[0] if tables else {}
        options = table.get("options", [])
        checker.check(
            "enum2.real-options",
            table.get("id") == 2
            and table.get("name") == "比较运算"
            and table.get("optionCount") == 5
            and len(options) == 5
            and {option.get("value") for option in options} == {100, 101, 102, 103, 104}
            and all(
                str(option.get("name", "")).startswith("比较运算_") for option in options
            ),
            f"tables={tables!r}",
        )

    data, _out = checker.expect(
        "enum-query", ["enums", "--query", "比较", "--limit", "10"], 0
    )
    if data is not None:
        tables = data.get("tables", [])
        checker.check(
            "enum-query.hits",
            data.get("total", 0) >= 1
            and any(table.get("id") == 2 for table in tables)
            and all(len(table.get("options", [])) > 0 for table in tables),
            f"total={data.get('total')!r} ids={[table.get('id') for table in tables]!r}",
        )
        checker.validate_schema("enum-query", data)

    data, _out = checker.expect("enum-unknown", ["enums", "--enum-id", "999999"], 2)
    if data is not None:
        checker.check(
            "enum-unknown.error-body",
            data.get("error", {}).get("code") == "ENUM_NOT_FOUND"
            and "999999" in str(data.get("error", {}).get("message", "")),
            f"error={data.get('error')!r}",
        )
        checker.validate_schema("enum-unknown", data)


def run_cluster_checks(checker: Checker) -> None:
    data, _out = checker.expect(
        "cluster-shop", ["cluster", "shop", "--graph-kind", "20000"], 0
    )
    if data is not None:
        cluster = data.get("cluster", {})
        nodes = data.get("nodes", [])
        ids = [node.get("definitionId") for node in nodes]
        checker.check(
            "cluster-shop.meta",
            cluster.get("id") == "shop"
            and "商店" in str(cluster.get("name", ""))
            and cluster.get("count") == 20
            and cluster.get("runtimeVerified") is False,
            f"cluster={cluster!r}",
        )
        checker.check(
            "cluster-shop.nodes",
            data.get("total") == 20
            and len(nodes) == 20
            and len(set(ids)) == 20
            and all(node.get("graphKind") == 20000 for node in nodes)
            and 702 in ids
            and all(node.get("grade", {}).get("level") == "L2" for node in nodes)
            and all(len(node.get("menuPaths", [])) >= 1 for node in nodes),
            f"total={data.get('total')!r} ids={ids!r}",
        )
        node702 = next((node for node in nodes if node.get("definitionId") == 702), {})
        checker.check(
            "cluster-shop.node702",
            node702.get("name") == "打开商店"
            and node702.get("side") == "server"
            and {"farming", "shop"} <= set(node702.get("clusters", [])),
            f"node702={node702!r}",
        )
        checker.validate_schema("cluster-shop", data)

    data, _out = checker.expect("cluster-shop-all-kinds", ["cluster", "shop"], 0)
    if data is not None:
        checker.check(
            "cluster-shop-all-kinds.total",
            data.get("total") == 20
            and len(data.get("nodes", [])) == 20
            and data.get("query", {}).get("graphKind") is None,
            f"total={data.get('total')!r} query={data.get('query')!r}",
        )

    # farming：跨簇 recipe 簇（discovery/index.json 的 crossClusterRecipe=true）。
    # 它的成员只在 discovery/clusters/farming.json，routes.json 的 clusters[] 里为空；
    # 早前按 routes 推导成员会让 cluster farming 返回 0 个节点，这里是该回归的守卫。
    data, _out = checker.expect(
        "cluster-farming", ["cluster", "farming", "--graph-kind", "20000"], 0
    )
    if data is not None:
        nodes = data.get("nodes", [])
        ids = [node.get("definitionId") for node in nodes]
        checker.check(
            "cluster-farming.membership",
            data.get("total") == 16
            and len(nodes) == 16
            and len(set(ids)) == 16
            and all(node.get("graphKind") == 20000 for node in nodes)
            and {307, 702} <= set(ids)
            and all("farming" in node.get("clusters", []) for node in nodes)
            and all(node.get("grade", {}).get("level") == "L2" for node in nodes)
            and all(len(node.get("menuPaths", [])) >= 1 for node in nodes),
            f"total={data.get('total')!r} ids={ids!r}",
        )
        checker.validate_schema("cluster-farming", data)

    data, _out = checker.expect("cluster-farming-all-kinds", ["cluster", "farming"], 0)
    if data is not None:
        checker.check(
            "cluster-farming-all-kinds.total",
            data.get("total") == 16 and len(data.get("nodes", [])) == 16,
            f"total={data.get('total')!r}",
        )

    data, _out = checker.expect("cluster-unknown", ["cluster", "nosuch"], 2)
    if data is not None:
        checker.check(
            "cluster-unknown.error-body",
            data.get("error", {}).get("code") == "CLUSTER_NOT_FOUND"
            and "nosuch" in str(data.get("error", {}).get("message", "")),
            f"error={data.get('error')!r}",
        )
        checker.validate_schema("cluster-unknown", data)


def run_search_checks(checker: Checker) -> None:
    data, out = checker.expect(
        "search-dict", ["search", "--query", "字典", "--limit", "10"], 0
    )
    if data is not None:
        results = data.get("results", [])
        checker.check(
            "search-dict.hits",
            data.get("total", 0) >= 10
            and len(results) == 10
            and any("字典" in str(item.get("name", "")) for item in results)
            and all(item.get("match") for item in results)
            and data.get("query", {}).get("limit") == 10,
            f"total={data.get('total')!r} names={[item.get('name') for item in results]!r}",
        )
        checker.validate_schema("search-dict", data)
    code2, out2, err2 = invoke(["search", "--query", "字典", "--limit", "10"])
    checker.check(
        "search-dict.deterministic",
        code2 == 0 and err2 == "" and out2 == out,
        f"second run exit={code2} identical={out2 == out}",
    )

    data, _out = checker.expect(
        "search-shop", ["search", "--query", "商店", "--graph-kind", "20000", "--limit", "5"], 0
    )
    if data is not None:
        results = data.get("results", [])
        ids = [item.get("definitionId") for item in results]
        checker.check(
            "search-shop.hits",
            data.get("total", 0) >= 5
            and len(results) == 5
            and all(item.get("graphKind") == 20000 for item in results)
            and 702 in ids,
            f"total={data.get('total')!r} ids={ids!r}",
        )
        checker.validate_schema("search-shop", data)

    # 功能簇别名展开依赖 clusters/<id>.json；只看 routes.json 的 clusters[] 会让
    # farming 的别名（种田 / 农场）永远 0 命中。
    data, _out = checker.expect("search-farming-alias", ["search", "--query", "种田"], 0)
    if data is not None:
        results = data.get("results", [])
        by_id = {item.get("definitionId"): item for item in results}
        checker.check(
            "search-farming-alias.hits",
            data.get("total", 0) >= 16
            and len(results) >= 16
            and 307 in by_id
            and 702 in by_id
            and "cluster:farming" in by_id[307].get("match", [])
            and "cluster:farming" in by_id[702].get("match", [])
            and "farming" in by_id[702].get("clusters", []),
            f"total={data.get('total')!r} ids={sorted(by_id)!r}",
        )
        checker.validate_schema("search-farming-alias", data)

    # graphKind 过滤必须作用在变体上（文档 §5.4 的示例命令就是这条）
    data, _out = checker.expect(
        "search-dict-graphkind",
        ["search", "--query", "字典", "--graph-kind", "20000", "--limit", "10"],
        0,
    )
    if data is not None:
        results = data.get("results", [])
        checker.check(
            "search-dict-graphkind.filter",
            data.get("total") == 13
            and len(results) == 10
            and all(item.get("graphKind") == 20000 for item in results)
            and data.get("query", {}).get("graphKind") == 20000,
            f"total={data.get('total')!r} kinds={[item.get('graphKind') for item in results]!r}",
        )
        checker.validate_schema("search-dict-graphkind", data)

    data, _out = checker.expect(
        "search-no-match", ["search", "--query", "不存在关键词xyz"], 2
    )
    if data is not None:
        checker.check(
            "search-no-match.error-body",
            data.get("error", {}).get("code") == "SEARCH_NO_MATCH"
            and data.get("total") == 0
            and data.get("results") == []
            and "不存在关键词xyz" in str(data.get("error", {}).get("message", "")),
            f"data={data!r}",
        )
        checker.validate_schema("search-no-match", data)


GRAPH_BUILT_REL = "data/m2/node-capability/evidence/graph-built-index.json"
GRAPH_BUILT_EXPECT = {
    73: "L3-LIVE-GRAPH-BUILT",
    307: "L3-LIVE-GRAPH-BUILT",
    259: "L3-LIVE-GRAPH-BUILT",
    702: "L3-LIVE-GRAPH-BUILT",
    14: "L3-LIVE-GRAPH-BUILT",
    2: "L3-LIVE-GRAPH-BUILT",
    1: "L3-LIVE-GRAPH-BUILT",
    71: "L3-LIVE-GRAPH-BUILT-BRIDGE",
    708: "L3-LIVE-GRAPH-BUILT-BRIDGE",
    710: "L3-LIVE-GRAPH-BUILT-BRIDGE",
    1788: "L3-LIVE-GRAPH-EDITED",
}
GRAPH_BUILT_KINDS = {
    "L3-LIVE-GRAPH-BUILT",
    "L3-LIVE-GRAPH-BUILT-BRIDGE",
    "L3-LIVE-GRAPH-EDITED",
    "L3-BIND-READBACK",
}


def run_graph_built_checks(checker: Checker) -> None:
    """graph-built 子命令：子类不得混称、source sha 可重算、L4/EDITED 边界。"""

    index_path = ROOT / GRAPH_BUILT_REL
    if not index_path.is_file():
        checker.check("graph-built.index-file", False, f"缺少 {GRAPH_BUILT_REL}")
        return
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index_sha = sha256_file(index_path)
    checker.check(
        "graph-built.index-file",
        index.get("counts", {}).get("definitions") == 11,
        f"counts={index.get('counts')!r}",
    )

    label = "graph-built-307"
    data, out = checker.expect(label, ["graph-built", "--definition-id", "307"], 0)
    checker.validate_schema(label, data)
    record = ((data or {}).get("records") or [{}])[0]
    checker.check(
        f"{label}.kind",
        record.get("kind") == "L3-LIVE-GRAPH-BUILT",
        f"kind={record.get('kind')!r}",
    )
    checker.check(
        f"{label}.graphIds",
        record.get("graphIds") == [1073741825],
        f"graphIds={record.get('graphIds')!r}",
    )
    checker.check(
        f"{label}.index-sha",
        (data or {}).get("indexSha256") == index_sha,
        f"reported={(data or {}).get('indexSha256')!r} actual={index_sha}",
    )

    label = "graph-built-71"
    data, out = checker.expect(label, ["graph-built", "--definition-id", "71"], 0)
    checker.validate_schema(label, data)
    record = ((data or {}).get("records") or [{}])[0]
    checker.check(
        f"{label}.kind",
        record.get("kind") == "L3-LIVE-GRAPH-BUILT-BRIDGE",
        f"kind={record.get('kind')!r}",
    )

    label = "graph-built-1788"
    data, out = checker.expect(label, ["graph-built", "--definition-id", "1788"], 0)
    checker.validate_schema(label, data)
    record = ((data or {}).get("records") or [{}])[0]
    checker.check(
        f"{label}.kind-edited-not-built",
        record.get("kind") == "L3-LIVE-GRAPH-EDITED",
        f"kind={record.get('kind')!r}",
    )
    checker.check(
        f"{label}.graphIds-1842-only",
        record.get("graphIds") == [1073741840],
        f"graphIds={record.get('graphIds')!r}",
    )
    checker.check(
        f"{label}.runtime-verified-false",
        record.get("runtimeVerified") is False,
        f"runtimeVerified={record.get('runtimeVerified')!r}",
    )

    label = "graph-built-999999"
    data, out = checker.expect(label, ["graph-built", "--definition-id", "999999"], 2)
    checker.check(
        f"{label}.error-code",
        ((data or {}).get("error") or {}).get("code") == "GRAPH_BUILT_NOT_FOUND",
        f"error={(data or {}).get('error')!r}",
    )

    label = "graph-built-list"
    data, out = checker.expect(label, ["graph-built", "--list"], 0)
    checker.validate_schema(label, data)
    records = (data or {}).get("records") or []
    got = {int(item["definitionId"]): item for item in records}
    checker.check(
        f"{label}.count",
        len(records) == 11 and (data or {}).get("count") == 11,
        f"records={len(records)} count={(data or {}).get('count')!r}",
    )
    detail_kinds = {d: got.get(d, {}).get("kind") for d in GRAPH_BUILT_EXPECT}
    checker.check(
        f"{label}.subkinds",
        all(got.get(d, {}).get("kind") == kind for d, kind in GRAPH_BUILT_EXPECT.items())
        and set(got) == set(GRAPH_BUILT_EXPECT),
        f"got={detail_kinds}",
    )
    checker.check(
        f"{label}.no-1788-built",
        got.get(1788, {}).get("kind") not in {"L3-LIVE-GRAPH-BUILT", "L3-LIVE-GRAPH-BUILT-BRIDGE"},
        f"1788.kind={got.get(1788, {}).get('kind')!r}",
    )
    checker.check(
        f"{label}.kinds-allowed",
        all(item.get("kind") in GRAPH_BUILT_KINDS for item in records),
        f"kinds={sorted({item.get('kind') for item in records})!r}",
    )
    sha_bad: list[str] = []
    missing: list[str] = []
    for item in records:
        for source in item.get("sources") or []:
            path = ROOT / source.get("path", "")
            if not path.is_file():
                missing.append(source.get("path", ""))
                continue
            if source.get("sha256") != sha256_file(path):
                sha_bad.append(source.get("path", ""))
    checker.check(
        f"{label}.sources-sha",
        not sha_bad and not missing,
        f"sha_bad={sha_bad[:3]!r} missing={missing[:3]!r}",
    )

    code_a, out_a, _err = invoke(["graph-built", "--definition-id", "307"])
    code_b, out_b, _err = invoke(["graph-built", "--definition-id", "307"])
    checker.check(
        "graph-built.deterministic",
        code_a == code_b == 0 and out_a == out_b,
        "same query produced different bytes",
    )
    checker.expect("graph-built-no-args", ["graph-built"], 3)
    checker.expect(
        "graph-built-both-flags",
        ["graph-built", "--definition-id", "307", "--list"],
        3,
    )


def run_schema_and_help_checks(checker: Checker) -> None:
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        checker.check("schema.json-parses", False, f"{type(exc).__name__}: {exc}")
        return
    defs = schema.get("$defs", {})
    const_commands = {
        definition.get("properties", {}).get("command", {}).get("const")
        for definition in defs.values()
        if isinstance(definition, dict)
    }
    checker.check(
        "schema.json-structure",
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
        and set(COMMANDS) <= const_commands
        and {"capabilityRecord", "port", "enumTable", "clusterNode", "errorEnvelope"} <= set(defs),
        f"$schema={schema.get('$schema')!r} commands={sorted(c for c in const_commands if c)!r}",
    )

    code, out, err = invoke(["--help"])
    checker.check(
        "help.exit",
        code == 0 and err == "",
        f"exit={code} stderr={err[:120]!r}",
    )
    checker.check(
        "help.commands",
        all(command in out for command in COMMANDS),
        f"missing={[c for c in COMMANDS if c not in out]!r}",
    )


def run_full_schema_check(checker: Checker) -> None:
    """对全部 929 条能力记录做 schema 校验，防止 schema 只覆盖手选的样本。"""

    if VALIDATOR is None:
        checker.note("schema.all-query-records", "jsonschema 不可用，跳过全量 schema 校验")
        return
    module = load_cli_module(checker)
    if module is None:
        checker.check(
            "schema.all-query-records", False, "无法加载 cli.py 模块（见 cli.module-load）"
        )
        return

    total = 0
    failures: list[str] = []
    for definition in module.manifest_index()["definitions"]:
        for variant_summary in definition["variants"]:
            definition_id = int(definition["definitionId"])
            graph_kind = int(variant_summary["graphKind"])
            _definition, entry, variant = module.lookup_variant(definition_id, graph_kind)
            payload = {
                "schemaVersion": 1,
                "ok": True,
                "command": "query",
                "query": {"definitionId": definition_id, "graphKind": graph_kind},
                "record": module.build_capability_record(_definition, entry, variant),
            }
            errors = sorted(VALIDATOR.iter_errors(payload), key=lambda error: list(error.path))
            total += 1
            if errors:
                failures.append(
                    f"{definition_id}/{graph_kind}: {list(errors[0].path)}: {errors[0].message}"
                )
    checker.check(
        "schema.all-query-records",
        total == 929 and not failures,
        f"validated={total} expected=929 failures={failures[:3]!r}",
    )


def run_cluster_membership_check(checker: Checker) -> None:
    """跨来源核对 31 个功能簇的成员口径。

    成员以 discovery/clusters/<id>.json 为准（含跨簇 recipe 簇 farming），必须与
    discovery/index.json 的 count 一致，且每个成员都能在 manifest 中按
    definitionId+graphKind 解析（解析失败就是 exit 1 的数据不一致）。
    """

    module = load_cli_module(checker)
    if module is None:
        checker.check("cluster-membership.consistency", False, "无法加载 cli.py 模块")
        return

    clusters = module.discovery_index()["clusters"]
    problems: list[str] = []
    for cluster in clusters:
        cluster_id = str(cluster["id"])
        members = module.cluster_members(cluster_id)
        declared = cluster.get("count")
        if declared != len(members):
            problems.append(f"{cluster_id}: members={len(members)} index.count={declared}")
        for definition_id, graph_kind in members:
            try:
                module.lookup_variant(definition_id, graph_kind)
            except module.CliError as exc:
                problems.append(f"{cluster_id}: {definition_id}/{graph_kind}: {exc.code}")
    checker.check(
        "cluster-membership.consistency",
        len(clusters) == 31 and not problems,
        f"clusters={len(clusters)} problems={problems[:3]!r}",
    )

    farming_routes = [
        route
        for route in module.discovery_routes()
        if "farming" in [str(c) for c in route.get("clusters") or []]
    ]
    checker.check(
        "cluster-membership.farming-cross-cluster",
        farming_routes == [] and len(module.cluster_members("farming")) == 16,
        f"routes-tagged={len(farming_routes)} members={len(module.cluster_members('farming'))}",
    )

    # 数据不一致路径：簇成员指向不存在的变体时必须报 DATA_INTEGRITY（exit 1），不能静默跳过。
    try:
        module._cluster_node(999999, 20000, "farming")
    except module.CliError as exc:
        checker.check(
            "cluster-membership.data-integrity",
            exc.code == "DATA_INTEGRITY"
            and exc.exit_code == 1
            and "999999" in exc.message,
            f"code={exc.code} exit={exc.exit_code} message={exc.message!r}",
        )
    else:
        checker.check(
            "cluster-membership.data-integrity", False, "成员缺变体时没有报 DATA_INTEGRITY"
        )

    # 防御路径：index 说簇里有节点、但成员口径算出 0 时，必须报 DATA_INTEGRITY 而不是返回 total:0。
    original = module._CLUSTER_MEMBERS_CACHE.get("farming")
    module._CLUSTER_MEMBERS_CACHE["farming"] = ()
    try:
        module.cmd_cluster(argparse.Namespace(cluster="farming", graph_kind=None, limit=500))
    except module.CliError as exc:
        checker.check(
            "cluster-membership.empty-cluster-guard",
            exc.code == "DATA_INTEGRITY" and exc.exit_code == 1,
            f"code={exc.code} exit={exc.exit_code} message={exc.message!r}",
        )
    else:
        checker.check(
            "cluster-membership.empty-cluster-guard",
            False,
            "簇成员为 0 但 index.count>0 时没有报 DATA_INTEGRITY",
        )
    finally:
        if original is None:
            module._CLUSTER_MEMBERS_CACHE.pop("farming", None)
        else:
            module._CLUSTER_MEMBERS_CACHE["farming"] = original


def main() -> int:
    checker = Checker()
    print(f"node-capability-api check :: cli={relative(CLI)} schema={relative(SCHEMA)}")
    print(f"python={sys.version.split()[0]} root={ROOT.as_posix()}")
    print("-" * 72)
    run_version_checks(checker)
    run_query_checks(checker)
    run_ports_checks(checker)
    run_enum_checks(checker)
    run_cluster_checks(checker)
    run_cluster_membership_check(checker)
    run_search_checks(checker)
    run_graph_built_checks(checker)
    run_schema_and_help_checks(checker)
    run_full_schema_check(checker)

    failed = checker.failed()
    passed = len(checker.results) - len(failed)
    print("-" * 72)
    if failed:
        print("FAILED assertions:")
        for item in failed:
            print(f"  - {item['name']}: {item['detail']}")
    print(
        f"RESULT ok={str(not failed).lower()} assertions={len(checker.results)} "
        f"passed={passed} failed={len(failed)} "
        f"schemaValidated={checker.schema_validated} notes={len(checker.notes)}"
    )

    result = {
        "artifact": "node-capability-api-check",
        "schemaVersion": 1,
        "ok": not failed,
        "assertionsTotal": len(checker.results),
        "passed": passed,
        "failed": len(failed),
        "checks": [
            {"name": item["name"], "ok": item["ok"]}
            | ({"detail": item["detail"]} if item["detail"] else {})
            for item in checker.results
        ],
        "notes": checker.notes,
        "cli": {"path": relative(CLI), "sha256": sha256_file(CLI)},
        "schema": {"path": relative(SCHEMA), "sha256": sha256_file(SCHEMA)},
    }
    result_path = ROOT / ".runtime/m2/node-capability/api/check-result.json"
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"result={relative(result_path)}")
    except OSError as exc:
        print(f"NOTE 无法写入 {relative(result_path)}: {exc}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
