#!/usr/bin/env python3
"""Offline world-frame compiler. Compatible with python -B -I -S."""
from pathlib import Path
import argparse
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import world_frame as wf


def write_new(path, value):
    # CLI output stays in this module's project runtime, never CWD-derived.
    target = Path(path)
    if not target.is_absolute():
        target = wf.ROOT / target
    allowed = (wf.ROOT / ".runtime/world-frame-20261017").resolve()
    for item in (target, *target.parents):
        if item.exists() or item.is_symlink():
            wf.require(not item.is_symlink() and not (getattr(item.lstat(), "st_file_attributes", 0) & 0x400),
                       "REPARSE_OUTPUT_PATH")
    target = target.resolve()
    wf.require(target.is_relative_to(allowed), "OUTPUT_MUST_BE_WORLD_FRAME_RUNTIME")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return str(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("compile", "compile-fixture"):
        p = sub.add_parser(name)
        p.add_argument("--points", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--quantization", required=True, choices=("exact", "nearest"))
        p.add_argument("--world-y-offset", type=float)
        if name == "compile":
            p.add_argument("--catalog-run", required=True)
            p.add_argument("--expected-identity-sha256")
        else:
            p.add_argument("--fixture", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--compiled", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result, _ = wf.read_json(wf.project_path(args.compiled, "compiled"))
            summary = wf.verify_compilation(result)
        else:
            points, points_sha = wf.read_json(wf.project_path(args.points, "points"))
            if args.command == "compile":
                result = wf.compile_points(args.catalog_run, points, quantization=args.quantization,
                                           expected_identity_sha256=args.expected_identity_sha256,
                                           world_y_offset=args.world_y_offset)
            else:
                fixture, _ = wf.read_json(wf.project_path(args.fixture, "fixture"))
                result = wf.compile_fixture(fixture, points, quantization=args.quantization,
                                            world_y_offset=args.world_y_offset)
            # Re-read points file too: provenance sources do not replace input binding.
            _, current_sha = wf.read_json(wf.project_path(args.points, "points"))
            wf.require(current_sha == points_sha, "POINT_DOCUMENT_CHANGED_DURING_COMPILATION")
            output = write_new(args.out, result)
            summary = dict(ok=True, output=output, mode=result["mode"],
                           compilationSha256=result["compilationSha256"],
                           pointDocumentFileSha256=points_sha, pointCount=result["pointCount"],
                           worldYOffset=result["worldYOffset"], nativeCalled=False, gameAccepted=False)
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return 0
    except wf.FrameError as exc:
        print(json.dumps(exc.result(), ensure_ascii=False, allow_nan=False))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(ok=False, code="WORLD_FRAME_IO_OR_SCHEMA_ERROR", error=str(exc),
                              nativeCalled=False, nativeExecuted=False, gameAccepted=False), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
