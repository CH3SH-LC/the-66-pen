"""Compatibility entry point for the versioned, read-only native inspection tool.

The original one-session memory probe is preserved under the update-repair
backup. Its fixed PID, module base and offsets must never be replayed. This
entry point now offers the same verify-disk/discover/prepare/decode workflow as
build_readonly_profile.py. Preparing a probe does not execute it or show UAC.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import runpy
import sys


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("action", choices=("verify-disk", "discover", "prepare", "decode"))
        parser.epilog = "Pass --help after an action for its options. No action runs automatically."
        parser.print_help()
        return 0 if args else 2
    if args[0] not in ("verify-disk", "discover", "prepare", "decode"):
        raise SystemExit("Use verify-disk, discover, prepare or decode; live execution is separate.")
    target = Path(__file__).resolve().parents[1] / "game-executor" / "build_readonly_profile.py"
    old_argv = sys.argv
    old_path = sys.path[:]
    try:
        sys.argv = [str(target), *args]
        sys.path.insert(0, str(target.parent))
        runpy.run_path(str(target), run_name="__main__")
    finally:
        sys.argv = old_argv
        sys.path[:] = old_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
