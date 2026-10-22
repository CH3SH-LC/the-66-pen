#!/usr/bin/env python3
"""Drive the editor interfaces end to end to produce a demo game.

This is the "real development test" the survey asks for: it takes the interfaces
that were only ever read off a decompiler, or only ever called in an earlier
session's diagnostic, and makes them run against the live editor, in order, with
every reply recorded.

It deliberately does NOT playtest. Starting a playtest is the one step left to
the user, because it is the step that writes a report into their account.

Each step's raw reply is written under .runtime/editor-bridge/demo/ so the run can
be audited afterwards without trusting this script's summary.

    python run-demo.py --plan        list the steps and stop
    python run-demo.py --run         execute, recording every reply
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parent
ROOT = BRIDGE.parents[1]
CLIENT = BRIDGE / "elevated-request.py"
OUT = ROOT / ".runtime" / "editor-bridge" / "demo"

EDITOR_PID = 39372

# The variant ops are the point of this run: the interface survey recorded
# "create/build/bind-gameloop-variant-core 从未调用" as an open gap. Each one is
# listed with the evidence it is expected to produce.
STEPS = [
    ("load", None, "inject a fresh bridge lease into the editor"),
    ("call", "ping", "prove the bridge is live and report its lease deadline"),
    ("call", "runtime-evidence", "record the level state BEFORE anything is created"),
    ("call", "create-gameloop-variant-core", "create the graph MW_Game_Loop_V3_20260917 (never called before)"),
    ("call", "build-gameloop-variant-core", "write 27 nodes into it (never called before)"),
    ("call", "bind-gameloop-variant-core", "bind it to the level entity (never called before)"),
    ("call", "export-gameloop-graph", "export the built graph to a .gia"),
    ("call", "runtime-evidence", "record the level state AFTER, for comparison"),
]


def call(kind: str, op: str | None, timeout: float) -> dict:
    argv = [sys.executable, str(CLIENT), kind]
    if kind == "load":
        argv += ["--target-pid", str(EDITOR_PID)]
    else:
        argv += ["--op", op, "--timeout", str(timeout)]
    # errors="replace": a reply is evidence even if one byte of it is undecodable,
    # and losing the whole document to a single bad byte is how a working call gets
    # recorded as a failure.
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout + 60)
    text = (proc.stdout or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "unparsed": text, "stderr": (proc.stderr or "").strip(), "exit": proc.returncode}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--skip-load", action="store_true",
                    help="the current revision is already injected; a second injection is always refused")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not args.run:
        for index, (kind, op, why) in enumerate(STEPS, 1):
            label = op if op else kind
            print(f"{index:>2}. {label:<34} {why}")
        print("\nplan only -- nothing executed. Re-run with --run.")
        return 0

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = Path(args.out) if args.out else (OUT / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {"startedUtc": stamp, "editorPid": EDITOR_PID, "steps": []}
    failures = 0
    steps = [s for s in STEPS if not (args.skip_load and s[0] == "load")]
    for index, (kind, op, why) in enumerate(steps, 1):
        label = op if op else kind
        started = time.time()
        print(f"[{index}/{len(STEPS)}] {label} ... ", end="", flush=True)
        result = call(kind, op, args.timeout)
        elapsed = round(time.time() - started, 2)
        ok = bool(result.get("ok")) or (kind == "load" and result.get("accepted"))
        # A step whose whole job is to be recorded is still worth keeping even if
        # the bridge refused it -- the refusal is the evidence.
        (out_dir / f"{index:02d}-{label.replace(' ', '-')}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        report["steps"].append({"step": label, "why": why, "ok": ok, "seconds": elapsed,
                                "summary": summarize(result)})
        print(("ok" if ok else "FAILED") + f" ({elapsed}s) {summarize(result)}")
        if not ok:
            failures += 1
            if kind == "load":
                print("cannot continue without a bridge lease")
                break
            # Every later step talks to the same lease, so once it has gone there is
            # nothing left to learn from the rest -- stop and say so.
            if "SCOPE_EXPIRED" in str(result.get("stderr", "")):
                print("lease expired; bump the revision with next-revision.ps1 and re-inject")
                break

    report["failures"] = failures
    (out_dir / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nrecorded under {out_dir}")
    print(f"steps={len(report['steps'])} failures={failures}")
    return 0 if failures == 0 else 1


def summarize(result: dict) -> str:
    if not result.get("ok"):
        return "error=" + str(result.get("error") or result.get("unparsed") or result)[:160]
    keys = ("status", "runId", "accepted", "bridgeVersion", "leaseDeadlineUtc",
            "editorLevelState", "graphId", "nodeCount", "bindingRequested",
            "exportPath", "rows", "removedGraphIds")
    picked = {k: result[k] for k in keys if k in result}
    return json.dumps(picked, ensure_ascii=False) if picked else f"{len(result)} keys"


if __name__ == "__main__":
    raise SystemExit(main())
