"""Create/check the self-excluding SHA-256 distribution manifest."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".runtime", "__pycache__", "bin", "obj", "node_modules", ".pytest_cache"}
GENERATED = {
    "data/ai-workbench/coverage.json", "data/ai-workbench/inventory-cache.json",
    "data/ai-workbench/asset-coverage.json", "data/ai-workbench/asset-libraries.json",
    "data/ai-workbench/node-coverage.json", "data/ai-workbench/script-coverage.json",
    "data/ai-workbench/tool-schemas.json", "data/ai-workbench/validation.json",
    "data/miliastra-toolkit/tools.json", "data/miliastra-toolkit/manifest.json",
    "data/node-workbench/recipes.json",
}


def entries():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.rglob("*")) if p.is_file() and not set(p.relative_to(ROOT).parts) & EXCLUDED
            and p.name != "MANIFEST.json" and p.suffix != ".sqlite"
            and p.relative_to(ROOT).as_posix() not in GENERATED
            and not p.name.startswith(("mcp.local.", "package-"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    a = parser.parse_args()
    current = entries()
    path = ROOT / "MANIFEST.json"
    if a.check:
        expected = json.loads(path.read_text())["files"]
        bad = sorted(k for k in current.keys() | expected.keys() if current.get(k) != expected.get(k))
        print(json.dumps({"ok": not bad, "files": len(current), "mismatches": bad}))
        return bool(bad)
    path.write_text(json.dumps({"schemaVersion": 1, "algorithm": "sha256",
                               "excludes": sorted(EXCLUDED | {"MANIFEST.json"}), "files": current}, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"files": len(current), "manifestSha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
