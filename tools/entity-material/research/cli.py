"""Static IL2CPP research. Explicit project-local --out; no game process access."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
import json
from pathlib import Path
from api import Research, validate_output, write_result


def number(value):
    return int(value, 0)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="Explicit project-local output directory, e.g. .life-dropstuff-out/research")
    p.add_argument("--stdout", action="store_true", help="Also print full JSON; otherwise print its artifact path")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("domains", help="Explain metadata index/enum/attribute domains and ABI boundaries")
    item = sub.add_parser("classes", help="Search exact metadata class names (no semantic aliases)")
    item.add_argument("--name", default=""); item.add_argument("--regex", action="store_true")
    item.add_argument("--offset", type=int, default=0); item.add_argument("--limit", type=int, default=100)
    for name, aliases in (("class", []), ("fields", []), ("field-offsets", ["fieldOffsets"]),
                          ("properties", ["props"]), ("methods", []), ("vtable", [])):
        item = sub.add_parser(name, aliases=aliases); item.add_argument("definition", type=number)
    item = sub.add_parser("method"); item.add_argument("index", type=number)
    item = sub.add_parser("field"); item.add_argument("definition", type=number)
    group = item.add_mutually_exclusive_group(required=True)
    group.add_argument("--ordinal", type=number); group.add_argument("--index", type=number)
    item = sub.add_parser("method-at"); item.add_argument("rva", type=number)
    item = sub.add_parser("type"); item.add_argument("index", type=number)
    item = sub.add_parser("literal"); item.add_argument("index", type=number)
    item = sub.add_parser("literals"); item.add_argument("text"); item.add_argument("--regex", action="store_true"); item.add_argument("--limit", type=int, default=100)
    item = sub.add_parser("usage"); item.add_argument("index", type=number)
    for name in ("bindings", "binding-xrefs"):
        item = sub.add_parser(name)
        group = item.add_mutually_exclusive_group(required=True)
        group.add_argument("--slot", type=number); group.add_argument("--literal", type=number); group.add_argument("--definition", type=number)
    item = sub.add_parser("usage-callers"); item.add_argument("groups", nargs="+", type=number)
    item = sub.add_parser("dump"); item.add_argument("rva", type=number); item.add_argument("--leaf-bytes", type=int, default=256)
    item = sub.add_parser("range"); item.add_argument("start", type=number); item.add_argument("end", type=number)
    item = sub.add_parser("rip-xrefs")
    item.add_argument("targets", nargs="+", type=number); item.add_argument("--start", type=number); item.add_argument("--end", type=number)
    item.add_argument("--all-unwind-functions", action="store_true", help="Expensive whole-image scan; no-unwind leaf code remains outside coverage")
    item.add_argument("--limit", type=int, default=10000)
    item = sub.add_parser("callers"); item.add_argument("targets", nargs="+", type=number); item.add_argument("--limit", type=int, default=10000)
    return p


def query(research, a):
    c = a.command
    if c == "domains": return research.domains()
    if c == "classes": return research.classes(a.name, regex=a.regex, offset=a.offset, limit=a.limit)
    if c == "class": return research.class_info(a.definition)
    if c in ("fields", "field-offsets", "fieldOffsets"): return research.fields(a.definition)
    if c in ("properties", "props"): return research.properties(a.definition)
    if c == "methods": return research.methods(a.definition)
    if c == "vtable": return research.vtable(a.definition)
    if c == "method": return research.method(a.index)
    if c == "field": return research.field(a.definition, ordinal=a.ordinal, index=a.index)
    if c == "method-at": return research.method_at(a.rva)
    if c == "type": return research.type(a.index)
    if c == "literal": return research.m.literal(a.index)
    if c == "literals": return research.literals(a.text, regex=a.regex, limit=a.limit)
    if c == "usage": return research.usage(a.index)
    if c in ("bindings", "binding-xrefs"):
        return (research.bindings if c == "bindings" else research.binding_xrefs)(slot=a.slot, literal=a.literal, definition=a.definition)
    if c == "usage-callers": return research.usage_callers(a.groups)
    if c == "dump": return research.dump(a.rva, leaf_bytes=a.leaf_bytes)
    if c == "range": return research.instructions(a.start, a.end)
    if c == "rip-xrefs": return research.rip_xrefs(a.targets, start=a.start, end=a.end, all_unwind=a.all_unwind_functions, limit=a.limit)
    if c == "callers": return research.callers(a.targets, limit=a.limit)
    raise ValueError("UNKNOWN_COMMAND")


def main(argv=None):
    try:
        a = parser().parse_args(argv)
        out = validate_output(a.out)  # Reject bad destinations before reading images.
        r = Research()
        data = query(r, a)
        result = r.envelope(a.command, data)
        result["arguments"] = {k:str(v) if isinstance(v, Path) else v for k,v in vars(a).items()}
        assembly = None
        if a.command in ("dump", "range"):
            assembly = "\n".join(i["rva"] + ": " + i["mnemonic"] + " " + i["operands"] for i in data["instructions"]) + "\n"
        command = {"fieldOffsets":"field-offsets", "props":"properties"}.get(a.command, a.command)
        artifact = write_result(out, command, result, assembly)
        response = result if a.stdout else dict(ok=True, command=a.command, artifact=str(artifact), gameConnected=False, nativeCalled=False,
                                               imageSha256=r.m.sha, metadataSha256=r.m.metadata_sha)
        if a.stdout:
            response["artifact"] = str(artifact)
        print(json.dumps(response, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, AssertionError, KeyError, OSError, UnicodeError, IndexError, OverflowError) as exc:
        print(json.dumps(dict(ok=False, error=type(exc).__name__ + ":" + str(exc), gameConnected=False, nativeCalled=False), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
