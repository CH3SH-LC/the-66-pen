"""Compile local source without changing PowerShell policy or contacting the game."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--research", action="store_true")
    a = parser.parse_args()
    projects = [
        "tools/editor-bridge/Bootstrap/Bootstrap.csproj",
        "tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj",
        "tools/editor-bridge/TestHost/TestHost.csproj",
    ]
    if a.research:
        projects.append("tools/editor-catalog/ilspy-dump/ilspy-dump.csproj")
    for project in projects:
        subprocess.run(["dotnet", "build", str(ROOT / project), "-c", "Release", "--nologo"], cwd=ROOT, check=True)
    if a.native:
        subprocess.run([str(ROOT / "tools/game-executor/native/build.cmd")], cwd=ROOT, check=True)
    print("Source build completed; game not contacted.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
