"""Build a local AI handoff with a content manifest; never publish or include live account state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/ai-workbench"
SKIP = {".git", "__pycache__", "node_modules", "bin", "obj", ".venv", "venv",
        "contract-staging"}
CODE = {".py", ".ps1", ".cs", ".cpp", ".h", ".hpp", ".json", ".md", ".txt",
        ".proto", ".csproj", ".props", ".targets", ".xml", ".yaml", ".yml", ".toml"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    target = (ROOT / args.out).resolve()
    if not target.is_relative_to(DATA) or target.suffix != ".zip":
        raise ValueError("PACKAGE_OUTPUT_MUST_BE_DATA_AI_WORKBENCH_ZIP")
    files = set()
    for root in ("tools", "docs", "backend/miliastra_agent",
                 "third_party/auto-miliastra/src/miliastra_agent"):
        base = ROOT / root
        if not base.exists():
            continue
        for folder, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for name in names:
                path = Path(folder) / name
                if path.suffix.lower() in CODE and not path.is_symlink():
                    files.add(path)
    for root in ("data/node-workbench", "data/node-contracts", "data/miliastra-toolkit",
                 "data/m2/assets", "data/m2/reference-pack"):
        base = ROOT / root
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.suffix in (".json", ".sqlite", ".md"):
                files.add(path)
    # Include every saved plan and method document, including recent main-street work.
    # Large image/mesh/media containers stay in the indexed local material library.
    for folder, dirs, names in os.walk(ROOT / "data"):
        dirs[:] = [d for d in dirs if d not in SKIP and d != "ai-workbench"]
        for name in names:
            path = Path(folder) / name
            if path.suffix in (".json", ".md", ".csv") and not path.is_symlink():
                files.add(path)
    for name in ("AI-START-HERE.md", "ai.py", "AGENT.md", "AGENTS.md", "GOAL.md",
                 "requirements.txt", "pyproject.toml"):
        if (ROOT / name).is_file():
            files.add(ROOT / name)
    for path in DATA.iterdir():
        if path.is_file() and path.name not in ("mcp.local.json", "inventory-cache.json", "package-result.json") and path.suffix in (".json", ".sqlite", ".md"):
            files.add(path)
    for path in (DATA / "examples").glob("*.json"):
        files.add(path)
    inventory = json.loads((DATA / "inventory-cache.json").read_text(encoding="utf-8"))
    external = [{"path": p, "bytes": v["bytes"], "sha256": v.get("sha256"),
                 "hashState": v["hashState"]}
                for p, v in inventory.items() if ROOT / p not in files]
    # Entries preserve locations for optional original resources, not personal sessions/saves.
    external = [v for v in external if not v["path"].endswith(".gil")]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".building.zip")
    manifest = []
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(files):
            relative = path.relative_to(ROOT).as_posix()
            blob = path.read_bytes()
            z.writestr(relative, blob)
            manifest.append({"path": relative, "bytes": len(blob), "sha256": digest(blob)})
        config = {"mcpServers": {"miliastra": {
            "command": "python", "args": ["-B", "-X", "utf8", "<EXTRACTED_ROOT>/ai.py", "serve"]}}}
        for name, value in (("data/ai-workbench/external-resources.json", external),
                            ("data/ai-workbench/mcp.template.json", config)):
            blob = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
            z.writestr(name, blob)
            manifest.append({"path": name, "bytes": len(blob), "sha256": digest(blob)})
        z.writestr("PACKAGE-MANIFEST.json", json.dumps({"schemaVersion": 1,
            "createdUtc": datetime.now(timezone.utc).isoformat(), "entries": manifest,
            "excludes": ["account saves", "active queues and sessions", "game installation binaries",
                         "large original resources", "credentials"],
            "bootstrap": "Read AI-START-HERE.md; run python -B ai.py configure"},
            ensure_ascii=False, indent=2).encode("utf-8"))
    # Independent ZIP readback: verify content hashes, not just ZIP CRC.
    with zipfile.ZipFile(temporary) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("PACKAGE_DUPLICATE_PATH")
        for item in manifest:
            if digest(z.read(item["path"])) != item["sha256"]:
                raise ValueError("PACKAGE_READBACK_HASH:" + item["path"])
    temporary.replace(target)
    result = {"ok": True, "path": str(target), "files": len(manifest),
              "bytes": target.stat().st_size, "sha256": digest(target.read_bytes()),
              "manifestReadbackVerified": True, "externalResources": len(external),
              "nativeCalled": False, "published": False}
    (DATA / "package-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
