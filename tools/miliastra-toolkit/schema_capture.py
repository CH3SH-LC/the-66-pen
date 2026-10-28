"""Extract real argparse contracts without parsing arguments or executing actions."""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def code_dependencies(entry):
    dependencies = {entry.resolve()}
    for loaded in tuple(sys.modules.values()):
        location = getattr(loaded, "__file__", None)
        if location:
            candidate = Path(location).resolve()
            if candidate.suffix == ".py" and candidate.is_relative_to(ROOT) and candidate.is_file():
                dependencies.add(candidate)
    pending, visited = list(dependencies), set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        if source.suffix != ".py":
            continue  # Non-Python declared dependencies are hashed, never parsed/imported.
        for item in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))):
            if isinstance(item, ast.Import):
                names = [alias.name for alias in item.names]
                bases = [source.parent, ROOT]
            elif isinstance(item, ast.ImportFrom):
                names = [item.module] if item.module else [alias.name for alias in item.names]
                bases = [source.parent, ROOT] if not item.level else [source.parents[item.level - 1]]
            else:
                continue
            for name in names:
                for base in bases:
                    target = base.joinpath(*name.split("."))
                    for candidate in (target.with_suffix(".py"), target / "__init__.py"):
                        if candidate.is_file() and candidate.is_relative_to(ROOT) and candidate not in dependencies:
                            dependencies.add(candidate)
                            pending.append(candidate)
    dependencies.discard(entry.resolve())
    return [{"path": candidate.relative_to(ROOT).as_posix(),
             "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
            for candidate in sorted(dependencies)]


class Captured(BaseException):
    def __init__(self, parser):
        self.parser = parser


def capture(self, *args, **kwargs):
    raise Captured(self)


def scalar(action):
    typename = getattr(action.type, "__name__", "")
    if typename in ("int", "uint", "node_uint", "definition_id", "identifier", "positive_int"):
        spec = {"type": "integer"}
        if typename != "int":
            spec.update(minimum=0, maximum=4294967295)
        if typename == "positive_int":
            spec["minimum"] = 1
    elif typename in ("float", "finite"):
        spec = {"type": "number"}
    else:
        spec = {"type": "string"}
    if action.choices is not None:
        choices = list(action.choices)
        if choices and all(type(v) is int for v in choices):
            spec["type"] = "integer"
        spec["enum"] = choices
    return spec


def action_contract(action, depth):
    if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
        return None
    if action.nargs in (argparse.REMAINDER, argparse.PARSER):
        raise ValueError("UNBOUNDED_REMAINDER:" + action.dest)
    flag = next((x for x in action.option_strings if x.startswith("--")), None)
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        spec = {"type": "boolean"}
        mode = "true" if isinstance(action, argparse._StoreTrueAction) else "false"
    elif isinstance(action, argparse._StoreConstAction):
        raise ValueError("UNSUPPORTED_STORE_CONST:" + action.dest)
    else:
        spec = scalar(action)
        mode = "append" if isinstance(action, argparse._AppendAction) else "value"
        if action.nargs not in (None, "?"):
            item = spec
            spec = {"type": "array", "items": item}
            if isinstance(action.nargs, int):
                spec.update(minItems=action.nargs, maxItems=action.nargs)
            elif action.nargs == "+":
                spec["minItems"] = 1
            else:
                spec["minItems"] = 0
        if mode == "append":
            spec = {"type": "array", "items": spec, "minItems": 1}
    help_text = action.help
    if help_text and help_text != argparse.SUPPRESS:
        spec["description"] = help_text
    default = action.default
    if isinstance(default, str) and default.startswith(str(ROOT)):
        default = Path(default).relative_to(ROOT).as_posix()
    if default not in (None, argparse.SUPPRESS) and isinstance(default, (str, int, float, bool, list)):
        spec["default"] = default
    required = bool(action.required or (not flag and action.nargs not in ("?", "*")))
    return {"name": action.dest, "flag": flag, "depth": depth, "mode": mode,
            "nargs": action.nargs, "required": required, "schema": spec,
            "path": getattr(action.type, "__name__", "") == "Path"}


def walk(parser, prefix=(), inherited=(), groups=(), depth=0):
    current = []
    try:
        for action in parser._actions:
            item = action_contract(action, depth)
            if item:
                current.append(item)
    except ValueError as exc:
        return [{"excluded": True, "command": list(prefix), "reason": str(exc)}]
    mutual = list(groups)
    for group in parser._mutually_exclusive_groups:
        mutual.append({"names": [a.dest for a in group._group_actions], "required": group.required})
    options = list(inherited) + current
    sub = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    if sub:
        rows = []
        for command, child in sub.choices.items():
            rows.extend(walk(child, prefix + (command,), options, mutual, depth + 1))
        return rows
    properties = {o["name"]: o["schema"] for o in options}
    schema = {"type": "object", "properties": properties,
              "required": [o["name"] for o in options if o["required"]],
              "additionalProperties": False}
    if mutual:
        schema["allOf"] = []
        for group in mutual:
            clauses = [{"required": [n], "not": {"anyOf": [{"required": [m]} for m in group["names"] if m != n]}}
                       for n in group["names"]]
            if not group["required"]:
                clauses.append({"not": {"anyOf": [{"required": [n]} for n in group["names"]]}})
            schema["allOf"].append({"oneOf": clauses})
    return [{"command": list(prefix), "inputSchema": schema, "options": options,
             "mutuallyExclusive": mutual, "description": parser.description or ""}]


def main():
    source = sys.argv[1]
    original_parse = argparse.ArgumentParser.parse_args
    original_known = argparse.ArgumentParser.parse_known_args
    argparse.ArgumentParser.parse_args = capture
    argparse.ArgumentParser.parse_known_args = capture
    sys.path.insert(0, str(ROOT))
    if source.startswith("module:"):
        module = importlib.import_module(source[7:])
        path = Path(module.__file__)
    else:
        path = ROOT / source
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location("_toolkit_capture_target", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    try:
        module.main()
    except Captured as result:
        if len(sys.argv) > 2 and sys.argv[2] == "--validate":
            argparse.ArgumentParser.parse_args = original_parse
            argparse.ArgumentParser.parse_known_args = original_known
            arguments = json.loads(sys.argv[3])
            parsed = result.parser.parse_args(arguments)
            print(json.dumps({"ok": True, "parsed": vars(parsed), "dispatchPerformed": False},
                             ensure_ascii=False, default=str))
            return 0
        output = {"source": str(path.relative_to(ROOT)).replace("\\", "/"),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "commands": walk(result.parser), "dispatchPerformed": False}
        # Resolve imports without executing lazy handlers such as demo's install.py.
        output["codeDependencies"] = code_dependencies(path)
        for extra in getattr(module, "TOOLKIT_CODE_DEPENDENCIES", ()):
            dependency = (ROOT / extra).resolve()
            if not dependency.is_relative_to(ROOT) or not dependency.is_file():
                raise ValueError("INVALID_DECLARED_TOOL_DEPENDENCY:" + str(extra))
            output["codeDependencies"].extend(code_dependencies(dependency))
            output["codeDependencies"].append({"path": dependency.relative_to(ROOT).as_posix(),
                                               "sha256": hashlib.sha256(dependency.read_bytes()).hexdigest()})
        output["codeDependencies"] = list({item["path"]: item for item in output["codeDependencies"]}.values())
        output["dependencyDiscovery"] = "loaded-modules-and-static-local-imports"
        print(json.dumps(output, ensure_ascii=False, default=str))
        return 0
    raise RuntimeError("PARSER_WAS_NOT_CAPTURED")


if __name__ == "__main__":
    raise SystemExit(main())
