#!/usr/bin/env python3
"""Build the demo game from scratch inside whichever level the editor has open.

WHAT THIS IS
    The interface survey in this project verified a set of graph-authoring
    operations one at a time, each against the level that happened to be open,
    each in its own bridge lease. That is a good way to learn an interface and a
    bad way to make a game: nothing ever assembled the pieces, and two of the
    operations turned out to have been written around the ids of the level they
    were first used in, so they refused in any other project.

    This drives the same operations as one build, in dependency order, in the
    editor's currently open level. It does not care which level that is -- it
    reads the level's entity list and builds against what is actually there. The
    only assumption is the one the editor itself makes: a level has an entity
    named 关卡实体, and graphs bind to it.

THE GAME
    A timed obstacle course, assembled from six graphs:

      MW_Platform_Calibration_20260916  spawn the starting platform, pin the origin
      MW_Route_Tiled_20260916           the route itself, as a tiled platform graph
      MW_Route_Placement_20260916       where the route's segments are placed
      MW_Character_Position_20260916    the player's start/respawn position
      MW_Course_Finish_20260916         the win condition
      MW_Game_Loop_20260916             score, timer, start/finish, fall-and-respawn

    Authoring and binding are separate phases because they have different
    preconditions, not for tidiness: build refuses a graph that is already bound,
    and the tiled route's bind refuses until the calibration graph's bind has been
    read back off the level entity. Splitting them also keeps each phase inside
    one five-minute bridge lease.

    python build-demo-game.py                     plan only
    python build-demo-game.py --phase author --run
    python build-demo-game.py --phase bind --run
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
RUNS = ROOT / ".runtime" / "editor-bridge" / "runs"
OUT = ROOT / ".runtime" / "editor-bridge" / "demo-game"

# Each phase is (op, why). The order is the dependency order -- create before
# build, build before bind, calibration bound before the tiled route is.
PHASES: dict[str, list[tuple[str, str]]] = {
    "author": [
        ("create-calibration-graph", "the starting platform's graph, empty and unbound"),
        ("build-calibration-graph", "6 nodes: on entity-create, spawn the platform prefab"),
        ("set-calibration-origin", "7th node: pin the platform at the level origin"),
        ("import-tiled-route", "39 nodes, imported from the fixed payload"),
        ("import-route-placement", "12 nodes: place the route's segments"),
        ("create-position-graph", "the player-position graph"),
        ("build-position-graph", "16 nodes: start and respawn position"),
        ("create-finish-graph", "the win-condition graph"),
        ("build-finish-graph", "23 nodes: reach the goal to finish"),
        ("create-gameloop-graph", "the game loop graph"),
        ("build-gameloop-graph", "29 nodes: score, timer, start, finish, fall"),
        ("repair-gameloop-score-order", "the scoreboard row constant the build writes wrong"),
        ("request-calibration-prefab", "ask the editor for the platform prefab instance"),
        ("runtime-evidence", "level state at the end of authoring"),
    ],
    "bind": [
        ("bind-calibration-graph", "bind first: the tiled route's bind checks it read back"),
        ("bind-tiled-route", "bind the route"),
        ("bind-position-graph", "bind the player position"),
        ("bind-finish-graph", "bind the win condition"),
        ("bind-gameloop-graph", "bind last: it requires the other three already bound"),
        ("runtime-evidence", "level state after binding"),
    ],
    "verify": [
        ("catalog", "independent read: every user graph, its id and node count"),
    ],
}

# The adapter allows at most two exports per bridge lease, thirty seconds apart:
# the export is an asynchronous send whose callback arrives later, and the gap is
# what keeps a second export's callback from being mistaken for the first's. So
# the graphs are exported two at a time, in separate leases, via --exports.
EXPORTABLE = [
    ("export-calibration-graph", "the starting platform and origin"),
    ("export-tiled-route", "the route"),
    ("export-position-graph", "the player position"),
    ("export-finish-graph", "the win condition"),
    ("export-gameloop-graph", "the game loop"),
]
EXPORTS_PER_LEASE = 2
EXPORT_WINDOW_SECONDS = 35.0

# How long to let the editor's own thread settle between a bind request and the
# readback the next op's precondition depends on.
SETTLE_SECONDS = 4.0
# The bind requests are asynchronous by nature, so a phase that depends on a
# readback gets one pause rather than a spin.
SETTLE_AFTER = {"bind-calibration-graph"}


def live_run_id() -> str | None:
    """The newest run whose lease is still open, or None.

    Same reasoning as elevated-request.latest_run_id: a run writes lease-closed.json
    when it ends, which bumps the directory mtime and makes a dead run look newest.
    """
    from datetime import datetime, timezone

    if not RUNS.exists():
        return None
    now = datetime.now(timezone.utc)
    live = []
    for d in RUNS.iterdir():
        settings = d / "bridge-settings.json"
        if not settings.exists():
            continue
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            expires = datetime.fromisoformat(data["expiresUtc"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if expires > now:
            live.append((expires, d.name))
    return max(live)[1] if live else None


def call(op: str, run_id: str, timeout: float) -> dict:
    proc = subprocess.run(
        [sys.executable, str(CLIENT), "call", "--op", op,
         "--run-id", run_id, "--timeout", str(timeout)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout + 60,
    )
    text = (proc.stdout or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "unparsed": text,
                "stderr": (proc.stderr or "").strip(), "exit": proc.returncode}


def summarize(reply: dict) -> str:
    """One line that says what happened, without claiming more than the reply does."""
    if reply.get("ok") is False:
        return "REFUSED: " + str(reply.get("error") or reply.get("exception")
                                 or reply.get("unparsed", ""))[:160]
    keys = ("status", "name", "graphId", "nodeCount", "resourceCount",
            "entityId", "bindingCount", "requested", "prefabId", "linked")
    parts = [f"{k}={reply[k]}" for k in keys if k in reply]
    return " ".join(parts) if parts else json.dumps(reply, ensure_ascii=False)[:160]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=sorted(PHASES), default=None)
    ap.add_argument("--all", action="store_true", help="run every phase in order")
    ap.add_argument("--exports", default=None,
                    help="comma-separated export ops for this lease (at most "
                         f"{EXPORTS_PER_LEASE}); a lease holds no more than that")
    ap.add_argument("--run", action="store_true", help="execute; without it, plan only")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--settle", type=float, default=SETTLE_SECONDS)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.exports:
        chosen = [o.strip() for o in args.exports.split(",") if o.strip()]
        known = {op for op, _ in EXPORTABLE}
        unknown = [o for o in chosen if o not in known]
        if unknown:
            print(f"not an exportable graph: {', '.join(unknown)}", file=sys.stderr)
            return 2
        if len(chosen) > EXPORTS_PER_LEASE:
            print(f"a lease holds at most {EXPORTS_PER_LEASE} exports; "
                  f"{len(chosen)} requested. Split them across leases.", file=sys.stderr)
            return 2
        PHASES["verify"] = [(o, dict(EXPORTABLE)[o]) for o in chosen] + PHASES["verify"]

    if not args.run:
        phases = sorted(PHASES) if args.all or not args.phase else [args.phase]
        for phase in phases:
            print(f"== {phase} ==")
            for op, why in PHASES[phase]:
                print(f"   {op:<32} {why}")
        print("\nplan only -- nothing executed. Re-run with --run.")
        return 0

    maybe = args.run_id or live_run_id()
    if maybe is None:
        print("no live bridge lease; inject one first "
              "(next-revision.ps1, then elevated-request.py load)", file=sys.stderr)
        return 2
    run_id = maybe

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    phases = sorted(PHASES) if args.all or not args.phase else [args.phase]
    label = "-".join(phases)
    out_dir = Path(args.out) if args.out else (OUT / f"{stamp}-{label}")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {"runId": run_id, "startedUtc": stamp, "phases": [], "steps": []}
    died = False
    for phase in phases:
        print(f"== {phase} ==")
        for index, (op, why) in enumerate(PHASES[phase]):
            started = time.time()
            reply = call(op, run_id, args.timeout)
            elapsed = round(time.time() - started, 2)
            # A reply that is a refusal is still evidence, so every one is kept.
            (out_dir / f"{phase}-{op}.json").write_text(
                json.dumps(reply, ensure_ascii=False, indent=1), encoding="utf-8")
            ok = reply.get("ok") is not False
            print(f"   {'ok  ' if ok else 'FAIL'} {op:<32} {elapsed:>6.1f}s  {summarize(reply)}")
            report["steps"].append({"phase": phase, "op": op, "why": why, "ok": ok,
                                    "seconds": elapsed, "summary": summarize(reply)})
            if not ok:
                # A dead lease fails every later op identically; say so once and stop
                # rather than filling the log with the same refusal.
                blob = json.dumps(reply, ensure_ascii=False)
                if "SCOPE_EXPIRED" in blob or "lease" in blob.lower():
                    print("   lease is gone -- bump the revision and inject again")
                    died = True
                    break
            if op in SETTLE_AFTER and args.settle > 0:
                time.sleep(args.settle)
            # An export holds a thirty-second observation window open; the next one
            # is refused while it lasts. Wait it out rather than discover that as a
            # refusal, but only when another export actually follows.
            rest = [o for o, _ in PHASES[phase][index + 1:]]
            if op.startswith("export-") and any(o.startswith("export-") for o in rest):
                print(f"        waiting {EXPORT_WINDOW_SECONDS:.0f}s for the export window ...")
                time.sleep(EXPORT_WINDOW_SECONDS)
        report["phases"].append(phase)
        if died:
            break

    report["failed"] = [s for s in report["steps"] if not s["ok"]]
    (out_dir / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(report['steps'])} steps, {len(report['failed'])} refused")
    print(f"recorded under {out_dir}")
    return 1 if report["failed"] or died else 0


if __name__ == "__main__":
    raise SystemExit(main())
