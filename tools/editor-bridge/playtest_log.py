#!/usr/bin/env python3
"""Make a playtest result machine-readable: turn the editor's runtime packet sink
into a printed timeline of every string the graph emitted.

WHY THIS EXISTS
---------------
A graph can be built, bound and saved on the live machine, but nobody observes it
*execute*. The scorecard says 0 of 15 runtime behaviours verified. The missing link
is: after a human clicks ``试玩``, what did the graph actually print?

That link already exists in the Adapter in three pieces, but nothing drives them as
one command and nothing decides what an EMPTY result means:

  * ``start-log-observer``      registers a read-only native packet sink (DispatchProxy)
  * ``enable-own-graph-logging`` sends native 3001 selecting our own graphs (needs an active sink)
  * ``log-observer-evidence``   reads back ``runLogSample.sample[]`` -- every structured log
                                record ACROSS ALL GRAPHS, each with observedUtc + graphName + bodyText
  * ``stop-log-observer``       detaches the sink

Source of each claim (this checkout):
  tools/editor-bridge/Adapter/EditorAdapter.cs:288  StartLogObserver (3002/3006 sink)
  tools/editor-bridge/Adapter/EditorAdapter.cs:379  ObservePacket gate: ``if(id!=3002 && id!=3006)return;``
  tools/editor-bridge/Adapter/RunLogSample.cs       the per-record reader (graphName + bodyText)
  tools/editor-bridge/Adapter/EditorAdapter.cs:498  the 3001 enable send (PHCi086M7o5)

THE RUNNER FIELD WHITELIST (asked explicitly by the task)
---------------------------------------------------------
No runner edit is required. ``elevated-runner.ps1:123`` parses the operation
allowlist *out of call-bridge.ps1's ValidateSet*, and that set already contains all
four ops above. The closed field schema (``elevated-runner.ps1:263``) is
``@('kind','runId','op','ids')``; these ops send exactly ``{kind,runId,op}`` and
``log-observer-evidence`` is additionally whitelisted read-only after reopen
(``reopen-lifecycle.ps1:116``). So this is NOT blocked on a missing op.

HONEST LIMITS (do not overclaim)
--------------------------------
  * Max single observation window is 120 s (``start-external-asset-observer`` ==
    ``StartLogObserver(120)``; ``start-log-observer`` is the 25 s variant). The lease
    is fixed to 25 or 120 (``EditorAdapter.cs:290``) and can only be attempted once
    per bridge session. Long runs need more than one session.
  * The record carries a ``graphName`` but NO entity id. Entity attribution is not
    in the packet; this tool never invents one.
  * A captured row proves a record was RECEIVED and which graph it names. It does not
    prove the record's meaning. Every emitted row still carries
    ``runtimeSemanticsVerified=false`` at its source.
  * ``playtestVerified`` / ``persistentSaveVerified`` are always false here: observing
    a print is not a durable save and not an acceptance of the run.

OFFLINE USE (run VERBATIM from the project root)
------------------------------------------------
  python tools/editor-bridge/playtest_log.py render --evidence <log-observer-evidence-response.json>
renders a recorded evidence file with no machine contact at all.

LIVE USE (run VERBATIM from the project root)
---------------------------------------------
  python tools/editor-bridge/playtest_log.py watch
starts the sink, enables own-graph logging, prints READY, polls until the lease
expires, prints the timeline, then stops. The human clicks 试玩 while it is polling.

Enable-by-default: there is NO ``--enable`` flag (its absence would be the bug this
runbook keeps catching). Passing ``--no-enable`` is the explicit opt-OUT, for when the
graphs are already ticked in the editor's graph-log filter tab. The argparse flag,
this docstring and PLAYTEST-LOG.md must all name the same option; the test
``DocumentedInvocationTests`` parses the lines above through the real parser.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Verdicts. Three-valued on purpose: "printed nothing" and "did not run" are
# different facts and must never collapse into one "no output".
# ---------------------------------------------------------------------------
VERDICT_PRINTS = "PRINTS_CAPTURED"
VERDICT_NO_PRINT = "RECORDS_NO_PRINT"
VERDICT_NO_TRAFFIC = "NO_LOG_TRAFFIC"
VERDICT_UNUSABLE = "EVIDENCE_UNUSABLE"

# Ops that carry no extra fields; see the module docstring's whitelist section.
OP_START_LONG = "start-external-asset-observer"   # 120 s sink
OP_START_SHORT = "start-log-observer"             # 25 s sink
OP_ENABLE = "enable-own-graph-logging"
OP_EVIDENCE = "log-observer-evidence"
OP_STOP = "stop-log-observer"

LEASE_SECONDS = {OP_START_SHORT: 25, OP_START_LONG: 120}
ALLOWED_INTERVAL_MIN = 1.0
ALLOWED_INTERVAL_MAX = 60.0
RUN_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                       r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ---------------------------------------------------------------------------
# Pure parsing / classification -- the testable core.
# ---------------------------------------------------------------------------
def iter_rows(evidence) -> list[dict]:
    """Return the emitted-string rows from a log-observer-evidence document.

    A row is kept only when ``bodyText`` is a non-empty string; rows whose body is
    an opaque type are dropped from the timeline (they are still counted in
    ``recordsSeen`` so the caller can tell "ran, no text" from "did not run").
    """
    if not isinstance(evidence, dict):
        return []
    sample = evidence.get("runLogSample")
    if not isinstance(sample, dict):
        return []
    rows = sample.get("sample")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row.get("bodyText")
        if not isinstance(text, str) or text == "":
            continue
        out.append({
            "utc": row.get("observedUtc"),
            "graph": row.get("graphName") or "<unnamed>",
            "text": text,
            "bodyType": row.get("bodyType"),
        })
    return out


def records_seen(evidence) -> int:
    if not isinstance(evidence, dict):
        return 0
    sample = evidence.get("runLogSample")
    if not isinstance(sample, dict):
        return 0
    value = sample.get("recordsSeen")
    return value if isinstance(value, int) else 0


def classify(evidence) -> str:
    """One of the four verdicts. Never guesses an entity or a meaning."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get("runLogSample"), dict):
        return VERDICT_UNUSABLE
    if iter_rows(evidence):
        return VERDICT_PRINTS
    if records_seen(evidence) > 0:
        return VERDICT_NO_PRINT
    return VERDICT_NO_TRAFFIC


def verdict_explanation(verdict: str, evidence) -> str:
    if verdict == VERDICT_PRINTS:
        return "Strings were emitted. See the timeline below."
    if verdict == VERDICT_NO_PRINT:
        n = records_seen(evidence)
        return (f"{n} structured log record(s) arrived but none carried readable text. "
                "The graph produced records without a print-string body, or the text body "
                "type was not the known carrier. Not a failure of the graph to run.")
    if verdict == VERDICT_NO_TRAFFIC:
        if isinstance(evidence, dict) and evidence.get("active") is False:
            return ("Observer inactive and zero log packets seen. The graph may not have run, "
                    "OR logging was not enabled for it (a graph not selected in the graph-log "
                    "filter tab emits no log). Absence of output here is NOT proof the graph "
                    "did not execute.")
        return ("Zero log packets and zero records. Same ambiguity: graph may not have run, "
                "or logging was off for it. Absence of output is NOT proof of non-execution.")
    return "No log-observer-evidence document (or no runLogSample field). Nothing to read."


def format_evidence(evidence, source: str = "(inline)", as_json: bool = False) -> str:
    verdict = classify(evidence)
    rows = iter_rows(evidence)
    ev = evidence if isinstance(evidence, dict) else {}
    sample = ev.get("runLogSample") if isinstance(ev.get("runLogSample"), dict) else {}
    if as_json:
        return json.dumps({
            "source": source,
            "verdict": verdict,
            "explanation": verdict_explanation(verdict, evidence),
            "observedPackets": ev.get("observedPackets"),
            "observedLogPackets": ev.get("observedLogPackets"),
            "recordsSeen": records_seen(evidence),
            "sampleLimited": sample.get("sampleLimited"),
            "observerActive": ev.get("active"),
            "rows": rows,
            "runtimeSemanticsVerified": False,
            "playtestVerified": False,
            "persistentSaveVerified": False,
        }, ensure_ascii=False, indent=2, sort_keys=True)

    lines = []
    lines.append(f"PLAYTEST LOG - {source}")
    lines.append(f"verdict: {verdict}")
    lines.append(f"  {verdict_explanation(verdict, evidence)}")
    lines.append(
        "counters: "
        f"observedPackets={ev.get('observedPackets')} "
        f"observedLogPackets={ev.get('observedLogPackets')} "
        f"recordsSeen={records_seen(evidence)} "
        f"sampleRows={len(sample.get('sample') or []) if isinstance(sample.get('sample'), list) else 0} "
        f"sampleLimited={sample.get('sampleLimited')} "
        f"observerActive={ev.get('active')}"
    )
    lines.append("")
    if not rows:
        lines.append("(no printed strings)")
    else:
        gwidth = max(len("graph"), max(len(r["graph"]) for r in rows))
        lines.append(f"{'timestamp (UTC)':<32}{'graph':<{gwidth + 2}}text")
        for r in rows:
            lines.append(f"{str(r['utc']):<32}{r['graph']:<{gwidth + 2}}{r['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Argument validation (pure; refused by name, never silently ignored).
# ---------------------------------------------------------------------------
def validate_watch_args(lease: str, interval: float, seconds=None) -> dict:
    if lease not in (OP_START_SHORT, OP_START_LONG):
        raise ValueError("LEASE_NOT_ALLOWED:" + str(lease))
    if not isinstance(interval, (int, float)) or interval != interval:
        raise ValueError("INTERVAL_INVALID")
    if interval < ALLOWED_INTERVAL_MIN or interval > ALLOWED_INTERVAL_MAX:
        raise ValueError(f"INTERVAL_OUT_OF_RANGE:{interval}")
    window = LEASE_SECONDS[lease]
    if seconds is not None:
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            raise ValueError("SECONDS_INVALID")
        window = min(float(seconds), float(LEASE_SECONDS[lease]))
    if window <= 0:
        raise ValueError("WINDOW_INVALID")
    return {"lease": lease, "interval": float(interval), "window": float(window)}


def validate_run_id(run_id) -> str:
    if run_id is None:
        return ""  # caller resolves the live run
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise ValueError("RUN_ID_INVALID:" + str(run_id))
    return run_id


def request_id_for(op: str, run_id: str, seq: int) -> str:
    """Deterministic per-dispatch id: a function of the request, never random.

    ``seq`` distinguishes successive polls of the SAME op so two identical reads
    never collide on one identity (the queue treats a reused id as the original
    operation, which would hand back a stale response).

    Truncated to 32 hex chars because elevated-request._request_id enforces exactly
    ``[0-9a-f]{32}``; a longer digest would be refused as QUEUE_REQUEST_ID_INVALID.
    """
    return hashlib.sha1(f"{op}|{run_id}|{seq}".encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Live orchestration. Everything machine-facing funnels through ``call`` so the
# whole sequence is testable with a fake and is a no-op under --dry-run.
# ---------------------------------------------------------------------------
class Runner:
    """Thin shell over elevated-request.py. Never touches the queue directly."""

    def __init__(self, root: Path, run_id: str):
        self.root = root
        self.run_id = run_id
        self.seq = 0

    def resolve_run_id(self) -> str:
        """Newest run whose lease is still open (mirrors elevated-request.latest_run_id)."""
        runs = self.root / ".runtime/editor-bridge/runs"
        now = _dt.datetime.now(_dt.timezone.utc)
        best = None
        for d in runs.iterdir() if runs.exists() else []:
            settings = d / "bridge-settings.json"
            if not settings.exists():
                continue
            try:
                data = json.loads(settings.read_text(encoding="utf-8-sig"))
                expires = _dt.datetime.fromisoformat(data["expiresUtc"])
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                continue
            if expires > now and (best is None or expires > best[0]):
                best = (expires, d.name)
        return best[1] if best else ""

    def call(self, op: str, dry_run: bool = False) -> dict:
        if not self.run_id:
            self.run_id = self.resolve_run_id()
        self.seq += 1
        rid = request_id_for(op, self.run_id or "no-live-run", self.seq)
        if dry_run:
            print(f"[dry-run] op={op} run={self.run_id or '<none>'} requestId={rid}", flush=True)
            return {"ok": True, "dryRun": True, "op": op, "runId": self.run_id, "requestId": rid}
        if not self.run_id:
            raise RuntimeError("NO_LIVE_RUN: run the load step first or pass --run-id")
        cmd = [sys.executable, str(self.root / "tools/editor-bridge/elevated-request.py"),
               "call", "--op", op, "--run-id", self.run_id,
               "--request-id", rid, "--timeout", "30"]
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8")
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(f"CALL_FAILED:{op}:{proc.stderr.strip()}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"CALL_NON_JSON:{op}:{proc.stdout[:200]}")


def watch(runner: Runner, cfg: dict, enable: bool, dry_run: bool,
          on_ready=None, sleep=time.sleep, now=time.monotonic) -> dict:
    """Run the full sequence once and return the last evidence document."""
    lease = cfg["lease"]
    runner.call(lease, dry_run)
    if enable:
        runner.call(OP_ENABLE, dry_run)
    if on_ready is not None:
        on_ready(runner.run_id)
    deadline = now() + cfg["window"]
    last = {}
    while True:
        last = runner.call(OP_EVIDENCE, dry_run)
        if dry_run or now() >= deadline:
            break
        sleep(min(cfg["interval"], max(0.0, deadline - now())))
    runner.call(OP_STOP, dry_run)
    return last


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    """The real CLI parser, factored out so tests can parse documented invocations.

    ``watch`` enables own-graph logging BY DEFAULT; ``--no-enable`` is the opt-out.
    There is deliberately NO ``--enable``: adding one would be a no-op alias whose
    absence is the exact documentation bug this module already suffered from.
    """
    ap = argparse.ArgumentParser(prog="playtest_log.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_render = sub.add_parser("render", help="offline: render a recorded evidence JSON")
    p_render.add_argument("--evidence", required=True)
    p_render.add_argument("--json", action="store_true")

    p_watch = sub.add_parser("watch", help="live: start sink, enable logging, poll, print, stop")
    p_watch.add_argument("--run-id", default=None)
    p_watch.add_argument("--lease", choices=(OP_START_SHORT, OP_START_LONG),
                         default=OP_START_LONG)
    p_watch.add_argument("--interval", type=float, default=3.0)
    p_watch.add_argument("--seconds", type=float, default=None,
                         help="cap the window (<= lease); default = full lease")
    p_watch.add_argument("--no-enable", action="store_true",
                         help="skip enable-own-graph-logging (rely on pre-selected graphs)")
    p_watch.add_argument("--dry-run", action="store_true",
                         help="print the exact op sequence without dispatching")
    p_watch.add_argument("--json", action="store_true")
    return ap


def main(argv=None) -> int:
    try:  # keep emitted graph text intact on a cp936 console
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    root = _project_root()

    if args.cmd == "render":
        raw = Path(args.evidence).read_text(encoding="utf-8-sig")
        try:
            evidence = json.loads(raw)
        except json.JSONDecodeError:
            evidence = None
        print(format_evidence(evidence, source=args.evidence, as_json=args.json))
        return 0 if classify(evidence) == VERDICT_PRINTS else 1

    # watch
    try:
        cfg = validate_watch_args(args.lease, args.interval, args.seconds)
        run_id = validate_run_id(args.run_id)
    except ValueError as ex:
        raise SystemExit(str(ex))
    runner = Runner(root, run_id)
    def ready(rid):
        print(f"READY run={rid} window={cfg['window']:.0f}s - click 试玩 in the editor now",
              flush=True)
    evidence = watch(runner, cfg, enable=not args.no_enable, dry_run=args.dry_run,
                     on_ready=ready)
    if args.dry_run:
        return 0
    print(format_evidence(evidence, source=f"run {runner.run_id}", as_json=args.json))
    return 0 if classify(evidence) == VERDICT_PRINTS else 1


if __name__ == "__main__":
    raise SystemExit(main())
