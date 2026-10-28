"""AI workbench entry point. Paths are resolved from this file, never the caller's cwd."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools/miliastra-toolkit"
sys.path.insert(0, str(TOOLS))
import toolkit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("search", "route", "describe", "error"):
        s = sub.add_parser(name)
        s.add_argument("text")
    for name in ("call", "plan"):
        s = sub.add_parser(name)
        s.add_argument("tool")
        g = s.add_mutually_exclusive_group()
        g.add_argument("--json")
        g.add_argument("--file", type=Path)
    sub.add_parser("serve")
    sub.add_parser("build")
    sub.add_parser("verify")
    sub.add_parser("configure")
    s = sub.add_parser("package")
    s.add_argument("--out", type=Path, default=Path("data/ai-workbench/handoff.zip"))
    args = p.parse_args()
    try:
        if args.command not in ("build", "configure") and not all((ROOT / path).is_file() for path in (
            "data/miliastra-toolkit/catalog.sqlite", "data/ai-workbench/knowledge.sqlite")):
            # No silent build on the MCP protocol stream; give one deterministic setup step.
            raise toolkit.ToolError("INDEX_NOT_BUILT: run python -B ai.py build once after cloning")
        if args.command == "serve":
            toolkit.serve(compact_tools=True)
            return 0
        if args.command in ("build", "verify", "package"):
            scripts = ["build.py", "build_knowledge.py"] if args.command == "build" else (
                ["validate_workbench.py"] if args.command == "verify" else ["package_workbench.py"])
            for script in scripts:
                command = [sys.executable, "-B", "-X", "utf8", str(TOOLS / script)]
                if args.command == "package":
                    command += ["--out", str(args.out)]
                result = subprocess.run(command, cwd=ROOT)
                if result.returncode:
                    return result.returncode
            return 0
        if args.command == "configure":
            path = ROOT / "data/ai-workbench/mcp.local.json"
            result = {"mcpServers": {"miliastra": {
                "command": sys.executable, "args": ["-B", "-X", "utf8", str(ROOT / "ai.py"), "serve"]}}}
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"ok": True, "config": str(path), "registeredInClient": False}, ensure_ascii=False))
            return 0
        mapping = {"status": ("knowledge.status", {}), "search": ("knowledge.search", {"query": getattr(args, "text", "")}),
                   "route": ("knowledge.route", {"task": getattr(args, "text", "")}),
                   "describe": ("tool.describe", {"name": getattr(args, "text", "")}),
                   "error": ("knowledge.errors", {"code": getattr(args, "text", "")})}
        if args.command in mapping:
            name, values = mapping[args.command]
        else:
            name = args.tool
            values = toolkit.read(ROOT / args.file) if args.file else json.loads(args.json or "{}")
        value = toolkit.invoke(name, values, plan=args.command == "plan")
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return 0 if value.get("ok") else 2
    except toolkit.ToolError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "next": "python -B ai.py error ERROR_CODE",
                          "nativeCalled": False}, ensure_ascii=False))
        return 2
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "next": "python -B ai.py error ERROR_CODE",
                          "nativeCalled": "unknown" if args.command == "call" else False,
                          "outcomeUncertain": args.command == "call",
                          "replayForbidden": args.command == "call"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
