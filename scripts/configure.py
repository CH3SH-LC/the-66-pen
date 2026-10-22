"""Configure only this checkout for a user-selected installation; no game calls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = r"C:\Games\Genshin Impact Game"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--powershell-host", required=True, type=Path)
    a = parser.parse_args()
    game, host = a.game_dir.resolve(), a.powershell_host.resolve()
    if not (game / "YuanShen.exe").is_file() or not (
        game / "BeyondAssets/BeyondAssistEditor/BeyondEditor.dll"
    ).is_file():
        parser.error("指定目录必须有 YuanShen.exe 和 BeyondEditor.dll；不会搜索其他目录。")
    if not host.is_file() or host.name.lower() not in ("pwsh.exe", "powershell.exe"):
        parser.error("指定已安装的 PowerShell 主程序绝对路径。")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    local = runtime / "installation.local.json"
    previous = json.loads(local.read_text())["gameDir"] if local.exists() else DEFAULT
    changed = []
    for base in [ROOT / "tools", ROOT / "backend"]:
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".ps1", ".cs", ".json"):
                continue
            if any(part in ("bin", "obj", "__pycache__", "node_modules") for part in p.parts):
                continue
            text = p.read_text(encoding="utf-8-sig")
            new = text.replace(previous.replace("\\", "\\\\"), str(game).replace("\\", "\\\\"))
            new = new.replace(previous, str(game))
            if text != new:
                p.write_text(new, encoding="utf-8", newline="\n")
                changed.append(p.relative_to(ROOT).as_posix())
    config = {"roots": [
        {"name": "project", "path": "%PROJECT_ROOT%", "read": True, "write": True},
        {"name": "game-install", "path": str(game), "read": True, "write": False},
    ]}
    (ROOT / "tools/editor-bridge/elevated-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    local.write_text(json.dumps({"gameDir": str(game), "python": sys.executable,
                                "powershellHost": str(host)}, indent=2), encoding="utf-8")
    def ps(s):
        return "'" + str(s).replace("'", "''") + "'"
    env = runtime / "environment.local.ps1"
    env.write_text(f"$env:MILIASTRA_GAME_DIR={ps(game)}\n$env:MILIASTRA_PYTHON={ps(sys.executable)}\n"
                   f"$env:MILIASTRA_POWERSHELL_HOST={ps(host)}\n", encoding="utf-8")
    print(json.dumps({"configured": True, "changedSourceFiles": changed,
                      "environment": str(env), "gameContacted": False,
                      "note": "仅重定位安装路径，二进制SHA/版本/签名检查保持。个人配置不要提交。"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
