"""Refresh public source-entry provenance without importing native tools."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "catalog/interfaces.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in document["interfaces"]}
    for file in sorted((ROOT / "tools").rglob("*.py")):
        if set(file.parts) & {"__pycache__", "tests", "test"} or file.name.startswith(("test", "validate")):
            continue
        relative = file.relative_to(ROOT).as_posix()
        identity = "cli." + relative[6:-3].replace("/", ".")
        if identity in rows:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        commands, arguments = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "add_parser" and node.args and isinstance(node.args[0], ast.Constant):
                    commands.append(str(node.args[0].value))
                if node.func.attr == "add_argument":
                    arguments.extend(str(a.value) for a in node.args if isinstance(a, ast.Constant))
        if not commands and not arguments:
            continue
        rows[identity] = {"id": identity, "name": file.stem, "family": relative.split("/")[1],
            "source": relative, "tool": relative, "line": 1, "args": ["--help"],
            "subcommands": sorted(set(commands)), "arguments": sorted(set(arguments)),
            "evidence": "source-implemented", "callable": "source-entry-see-help-and-prerequisites",
            "runtimeVerifiedThisRelease": False}
    for row in rows.values():
        file = ROOT / row["source"]
        if not file.is_file():
            raise ValueError("SOURCE_MISSING:" + row["source"])
        row["sourceSha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    document.update(snapshotDate="2026-10-28", interfaces=list(rows.values()))
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = ["# 接口与工具目录", "", "源码实现入口；完整参数用 `pen.py ai describe 工具名` 查询。",
             "入口计数不等于游戏功能数，静态候选和实机验收分开记录。", "",
             "| 接口 | 工具族 | 实现 |", "|---|---|---|"]
    lines += [f"| `{r['id']}` | {r['family']} | [{r['source']}](../{r['source']}) |" for r in rows.values()]
    (ROOT / "docs/INTERFACES.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"interfaces": len(rows), "gameAccessed": False}))


if __name__ == "__main__":
    main()
