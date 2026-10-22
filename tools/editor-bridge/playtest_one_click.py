#!/usr/bin/env python3
"""playtest_one_click.py -- the ONE run a human click can land inside.

WHY THIS EXISTS
---------------
``docs/gameplan/PLAYTEST-ONE-CLICK.md`` names the single human click
(**系统菜单 -> 【试玩】**) and the three outcomes that click can produce. What it does
NOT do is hold the pieces around that click in the one order the measurement allows:

  * the observer lease is a **fixed 120 s** and can be armed **once per scope**
    (``Adapter/EditorAdapter.cs:290`` -> ``OBSERVER_ALREADY_ATTEMPTED``);
  * the capture buffer (``runLogSample``) lives on the **scope's own** ``EditorAdapter``
    (``ManagedBridge/BridgeServer.cs:59`` ``_adapter=new()`` per injection), so the
    read-back must happen in the **same scope** that armed it -- a new ``load`` starts
    an empty buffer;
  * the scope's own lease is **5 minutes** (``new-scope.ps1`` ``expiresUtc``).

So the only sequence that can work is ONE choreographed run, inside ONE scope:

    load  ->  arm(120s)  ->  enable  ->  [ HUMAN CLICKS HERE ]  ->  poll  ->  stop

This script is that one run. It arms, then prints a LOUD ``CLICK NOW`` banner telling the
human **exactly** when and what to click, then polls the read-only read-back every few
seconds for the full window, then prints the captured sample -- and it is safe to leave
unattended: with nobody there it walks the whole window and exits with a named
``NO_LOG_TRAFFIC``, never hanging and never writing a save, an entity or a graph.

WHAT IT TOUCHES (and what it must never touch)
----------------------------------------------
Machine actions, all read-only or observer-only:
  ``elevated-request.py load``             -- mints+injects a fresh bridge scope (no UAC)
  ``start-external-asset-observer``        -- the 120 s read-only packet sink
  ``enable-own-graph-logging``            -- native 3001 selecting our own graphs
  ``log-observer-evidence``  (polled)     -- read-only read-back of the sink
  ``stop-log-observer``                   -- detach
It NEVER writes a save, never creates/deletes an entity or a graph, and never touches the
elevated helper's lifecycle. Every op is already in the runner's allowlist (re-read from
``call-bridge.ps1``'s ValidateSet per request), so no helper restart and no UAC.

DOES THE HUMAN STILL TICK ANYTHING IN 节点图筛选?
------------------------------------------------
**No.** The enable step now selects the graph itself: ``enable-own-graph-logging`` selects
the live graphs whose stored name starts with ``MW_`` (verified live: selection
``own-graphs-live:name-prefix=MW_``, 7 ids including ``1073741831 = MW_API_DEMO_RUN2``).
This script VERIFIES that the requested graph is in the returned selection and refuses by
name if it is not. The 节点图筛选 tick is therefore only an **optional fallback** for the
case where a run still ends ``NO_LOG_TRAFFIC`` (that the bridge enable alone makes the
game forward prints is not yet independently proven). The banner prints it as such.

USAGE (run VERBATIM from the project root)
------------------------------------------
  python tools/editor-bridge/playtest_one_click.py channels        # list the channels, dispatch nothing
  python tools/editor-bridge/playtest_one_click.py run --dry-run   # print the op plan only
  python tools/editor-bridge/playtest_one_click.py run             # the one run (module-probe profile)
  python tools/editor-bridge/playtest_one_click.py run --expect demo   # the MW_API_DEMO_RUN2 profile
  python tools/editor-bridge/playtest_one_click.py run --no-native   # skip the native entity sampler
  python tools/editor-bridge/playtest_one_click.py run --no-gil    # skip the live .gil hash sampler

WHICH GRAPH (the --expect profile)
----------------------------------
The click is FOR ONE graph, and each graph can print only its own strings, so the string set
is a PROFILE, selected with --expect:

  * modprobe (the DEFAULT) -- MW_API_MODPROBE, the per-module probe: 7 lines, one per module,
    on a LINEAR chain, so a capture is a PREFIX and the first missing line names the abort.
  * demo -- MW_API_DEMO_RUN2, the older branching demo: four literals, one printed per run.

A capture whose text is in NEITHER set is FOREIGN_PRINT: nothing in it is attributed to us.
The expected line set of the active profile is printed in the CLICK-NOW banner before you click.

ONE CLICK, ALL CHANNELS
-----------------------
A human click inside a 120 s window is scarce, so this run attaches every read-only
observable that is (a) readable, (b) non-constant and (c) compatible with the window
(see ``.runtime/scratch/CAPTURE-MATRIX.md``). Beside the packet sink it already drives, it
adds: the ``packetKinds`` histogram and observer liveness (both free -- same evidence
call), the live ``.gil`` sha256 (filesystem, no helper), and a read-only native ``inspect``
(entity count over time, through ``discover_current_level.py --queue-dir``). The final
report is one table with a per-channel verdict, printed ALONGSIDE (never instead of) the
existing outcome classifier.

THE ONE RULE THE TABLE ENCODES: **only ``log-evidence`` moves iff OUR graph ran.** Every
other channel moves for reasons of its own -- the observer's lifecycle, a keepalive count,
a save, a scene edit. So the channels are split by ROLE, structurally:

  * ``log-evidence`` is DIAGNOSTIC. It may say CHANGED / UNCHANGED / UNREADABLE, and its
    CHANGED is the only execution signal the table carries.
  * every other channel is CONTEXT. It may **never** print the word CHANGED -- its verdicts
    are MOVED / STILL / UNREADABLE, and MOVED means only "this value moved for some
    reason". A context channel is also compared on a MEANING KEY, so pure transport noise
    (a keepalive count climbing, the sink's own counters) cannot move it.

The queue path cannot carry an id to this enable op (the runner's closed schema admits
``ids`` only for its node-query ops, and ``elevated-request.py`` refuses ``--ids`` on any
other op by name), so ``--graph-name`` / ``--graph-id`` are used to **verify the returned
selection**, not to steer it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ``playtest_log`` is the same-directory sibling and the single source of truth for how a
# ``log-observer-evidence`` document is walked (row extraction, ``recordsSeen``). Import it
# rather than copying that logic, so one change to the document shape fixes both. The
# explicit sys.path insert keeps this working both as ``python .../playtest_one_click.py``
# and when a test loads this module by file path with importlib.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import playtest_log as _pl  # noqa: E402

# --- ops (all already in the runner's allowlist) -----------------------------
OP_LOAD = "load"                                   # kind=load, not a call op
OP_ARM = "start-external-asset-observer"           # 120 s packet sink
OP_ENABLE = "enable-own-graph-logging"             # native 3001
OP_EVIDENCE = "log-observer-evidence"              # read-only read-back
OP_STOP = "stop-log-observer"

OBSERVER_LEASE_SECONDS = 120.0
QUEUE_REL = ".runtime/editor-bridge/elevated-queue"
RUNS_REL = ".runtime/editor-bridge/runs"
DEFAULT_GRAPH_NAME = "MW_API_DEMO_RUN2"
DEFAULT_GRAPH_ID = 1073741831

# The ONLY strings MW_API_DEMO_RUN2 can emit (four print leaves, one line per execution).
DEMO_LITERALS = ("背包容量偏低", "收获完成", "作物不足但货币充足", "作物不足")
DEMO_DEFAULT_LITERAL = "作物不足"

# ---------------------------------------------------------------------------
# GRAPH PROFILES -- WHICH graph the one click is for (2026-10-12, WAVE-29AT)
# ---------------------------------------------------------------------------
# THE DEFECT THIS CLOSES: this supervisor used to be hardwired to ``MW_API_DEMO_RUN2`` and
# its four branch literals, while the graph that makes ONE click *maximally informative* --
# ``MW_API_MODPROBE`` (``tools/gameplan/demo/farming_module_probe.py``) -- prints a DIFFERENT
# seven-string set (``W29AI...``), one per module. A capture of that graph used to classify
# as ``FOREIGN_PRINT`` with ``captured_literals == []``: the click happened, the graph ran,
# and the tool said "not ours". So the target graph is now an explicit PROFILE, and the
# profile decides the graph name the enable selection must contain AND the classifier.
#
# The two profiles are NOT interchangeable and neither is a superset: each names the exact
# strings its graph can print. Adding a profile means adding its string set here (never
# guessing one at runtime).
PROFILE_DEMO = "demo"          # MW_API_DEMO_RUN2: four branch literals, one print per run
PROFILE_MODPROBE = "modprobe"  # MW_API_MODPROBE:  one line per module, a LINEAR chain

#: graph name -> profile key. The profile's graph name is the enable-selection gate.
PROFILE_GRAPH_NAME = {
    PROFILE_DEMO: DEFAULT_GRAPH_NAME,
    PROFILE_MODPROBE: "MW_API_MODPROBE",
}

MODPROBE_GRAPH_NAME = PROFILE_GRAPH_NAME[PROFILE_MODPROBE]

#: ``(owner, text)`` in EXECUTION-CHAIN order -- entry probe first, end marker last.
#: A MIRROR of ``farming_module_probe.PREDICTED_PRINTS`` (which is itself a re-derivation
#: of the plan by ``runtime_prediction.predict``). It is kept a literal here so this tool
#: stays standalone, and ``tools/gameplan/tests/test_repo_consistency.py`` pins it EQUAL to
#: the demo's predicted set -- so the two cannot drift silently (the drift is the defect).
MODPROBE_MODULE_PRINTS = (
    ("entry", "W29AI模块探针入口已触发"),
    ("M4-inventory", "W29AI-M4-背包容量已扩容"),
    ("M3-item", "W29AI-M3-道具已发放"),
    ("M2-currency", "W29AI-M2-货币已发放"),
    ("M1-interaction", "W29AI-M1-碰撞触发器已激活"),
    ("M5-shop", "W29AI-M5-商店已打开"),
    ("end", "W29AI模块探针结束"),
)
MODPROBE_PRINTS = tuple(text for _owner, text in MODPROBE_MODULE_PRINTS)
MODPROBE_TEXT_TO_MODULE = {text: owner for owner, text in MODPROBE_MODULE_PRINTS}

# --- outcomes ----------------------------------------------------------------
# The three named by docs/gameplan/PLAYTEST-ONE-CLICK.md §3 ...
OUT_CAPTURED_DEFAULT = "PRINTS_CAPTURED_DEFAULT_LITERAL"   # (a) 作物不足
OUT_CAPTURED_OTHER = "PRINTS_CAPTURED_OTHER_BRANCH"        # (b) a different demo literal
OUT_NO_TRAFFIC = "NO_LOG_TRAFFIC"                          # (c) no records at all
# ... plus the honest edge cases, so nothing ever collapses into one "no output":
OUT_NO_PRINT = "RECORDS_NO_PRINT"        # records arrived, none carried readable text
OUT_FOREIGN = "FOREIGN_PRINT"            # text arrived, but not one of our four literals
OUT_UNUSABLE = "EVIDENCE_UNUSABLE"       # no evidence document / no runLogSample
OUT_LOAD_REFUSED = "SCOPE_LOAD_REFUSED"
OUT_ARM_REFUSED = "OBSERVER_ARM_REFUSED"
OUT_ENABLE_REFUSED = "LOG_ENABLE_REFUSED"
OUT_GRAPH_NOT_SELECTED = "GRAPH_NOT_IN_SELECTION"
OUT_CALL_UNCERTAIN = "CALL_TIMEOUT_OUTCOME_UNCERTAIN"
#: The module-probe profile's capture outcome: at least one of the seven W29AI lines arrived.
#: It is a CAPTURE (exit 0) exactly like the demo's PRINTS_CAPTURED_* -- the chain shape is
#: read off ``moduleCapture`` (a prefix => the first abort is named).
OUT_MODPROBE = "MODPROBE_CAPTURED"

_CAPTURED = (OUT_CAPTURED_DEFAULT, OUT_CAPTURED_OTHER, OUT_MODPROBE)
_REFUSALS = (OUT_LOAD_REFUSED, OUT_ARM_REFUSED, OUT_ENABLE_REFUSED, OUT_GRAPH_NOT_SELECTED)


def exit_code_for(outcome: str) -> int:
    """0 captured, 1 a completed capture that found nothing actionable, 2 a named
    refusal (nothing downstream can be evidence), 3 an uncertain/timeout transport."""
    if outcome in _CAPTURED:
        return 0
    if outcome in _REFUSALS:
        return 2
    if outcome == OUT_CALL_UNCERTAIN:
        return 3
    return 1


# ---------------------------------------------------------------------------
# Pure classification (over the documented evidence shape only).
# ---------------------------------------------------------------------------
def text_rows(evidence) -> list[dict]:
    """Readable-text rows, via the sibling module's parser (single source of truth)."""
    return _pl.iter_rows(evidence)


def records_seen(evidence) -> int:
    return _pl.records_seen(evidence)


def captured_literals(evidence) -> list[str]:
    """The demo print literals present in the sample, sorted. Never invents one."""
    return sorted({r["text"] for r in text_rows(evidence) if r["text"] in DEMO_LITERALS})


def classify_outcome(evidence) -> str:
    """Total classifier. The doc's three outcomes are the first three branches."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get("runLogSample"), dict):
        return OUT_UNUSABLE
    rows = text_rows(evidence)
    if rows:
        seen = {r["text"] for r in rows}
        if seen & set(DEMO_LITERALS):
            return OUT_CAPTURED_DEFAULT if DEMO_DEFAULT_LITERAL in seen else OUT_CAPTURED_OTHER
        return OUT_FOREIGN
    if records_seen(evidence) > 0:
        return OUT_NO_PRINT
    return OUT_NO_TRAFFIC


def classify_module_probe(evidence) -> str:
    """Total classifier for the LINEAR module-probe graph. A capture is a PREFIX.

    Same shape of argument as :func:`classify_outcome`, a different string set: only the
    seven ``W29AI`` lines are ours. Anything else is ``OUT_FOREIGN`` -- never attributed.
    """
    if not isinstance(evidence, dict) or not isinstance(evidence.get("runLogSample"), dict):
        return OUT_UNUSABLE
    rows = text_rows(evidence)
    if rows:
        seen = {r["text"] for r in rows}
        if seen & set(MODPROBE_PRINTS):
            return OUT_MODPROBE
        return OUT_FOREIGN
    if records_seen(evidence) > 0:
        return OUT_NO_PRINT
    return OUT_NO_TRAFFIC


def module_probe_capture(evidence) -> dict:
    """Attribute a module-probe capture to the modules whose nodes executed.

    The probe chain is linear (``_CHAIN_ORDER`` in ``farming_module_probe``), so a capture
    is a **prefix** of :data:`MODPROBE_PRINTS`: the modules whose line is present ran, and
    the first missing line names where the chain stopped. Pure: reads the sample only.
    """
    seen = [r["text"] for r in text_rows(evidence)]
    ours = set(MODPROBE_TEXT_TO_MODULE)
    captured = [t for t in MODPROBE_PRINTS if t in seen]
    missing = [t for t in MODPROBE_PRINTS if t not in seen]
    return {
        "capturedOrder": captured,
        "modulesRan": [MODPROBE_TEXT_TO_MODULE[t] for t in captured],
        "modulesMissing": [MODPROBE_TEXT_TO_MODULE[t] for t in missing],
        "firstMissing": missing[0] if missing else None,
        "missing": missing,
        "foreign": sorted({t for t in seen if t and t not in ours}),
        "complete": not missing,
    }


def classify_with_profile(profile: str, evidence) -> str:
    """Dispatch the classifier by PROFILE -- the one place the two string sets part ways."""
    if profile == PROFILE_MODPROBE:
        return classify_module_probe(evidence)
    return classify_outcome(evidence)


def profile_expected_lines(profile) -> tuple:
    """The exact strings the profile's graph can print, in order.

    The module probe is a LINEAR chain, so its full ordered set IS the prediction (a capture
    is a prefix). The demo BRANCHES, so no single ordered set exists offline -- its four
    leaves are listed in :data:`DEMO_LITERALS` but which one fires is config-dependent, so
    this returns ``()`` rather than a line the graph may never print.
    """
    if profile == PROFILE_MODPROBE:
        return MODPROBE_PRINTS
    return ()


def outcome_explanation(outcome: str, evidence) -> str:
    if outcome == OUT_CAPTURED_DEFAULT:
        return ("The graph RAN: entry 71 fired and BOTH gate_item and gate_money took the "
                "false arm -- the default, no-template free case the offline model predicts. "
                "`作物不足` is produced only by print_short (nodeId 17).")
    if outcome == OUT_CAPTURED_OTHER:
        lits = captured_literals(evidence)
        return ("The graph RAN, but a different branch than predicted (" + ", ".join(lits) +
                "). Each of the four literals is a distinct, self-describing arm; the bound "
                "entity's components differ from the model's assumption.")
    if outcome == OUT_MODPROBE:
        cap = module_probe_capture(evidence)
        if cap["complete"]:
            return ("The graph RAN end to end: all five module nodes executed "
                    "(M4/M3/M2/M1/M5) and the chain reached its end marker. A module NODE "
                    "executing is NOT proof the module's EFFECT landed (see the runbook's "
                    "honesty line).")
        return ("The graph RAN and the chain stopped at " +
                (cap["firstMissing"] or "?") + ": modules that ran = " +
                (", ".join(cap["modulesRan"]) or "(none)") +
                ". The line right AFTER the last captured one names where it died.")
    if outcome == OUT_NO_TRAFFIC:
        if isinstance(evidence, dict) and evidence.get("active") is False:
            return ("Observer inactive and zero log packets. The graph may not have run, OR "
                    "logging was not enabled for it. Absence of output is NOT proof of "
                    "non-execution -- see PLAYTEST-ONE-CLICK.md §3(c).")
        return ("Zero log packets and zero records. Same ambiguity: the graph may not have "
                "run, or logging was off for it. Absence of output is NOT proof of "
                "non-execution.")
    if outcome == OUT_NO_PRINT:
        return (f"{records_seen(evidence)} structured log record(s) arrived but none carried "
                "readable text. Records without a print-string body, or an unknown body type.")
    if outcome == OUT_FOREIGN:
        return ("Text was captured, but none is one of the four demo literals; this is not "
                "this graph's output (foreign/other-graph traffic). Attribute nothing.")
    if outcome == OUT_LOAD_REFUSED:
        return ("The fresh scope never became ready. Most likely cause: the SAME bridge "
                "revision was already injected into this process (one injection per revision "
                "per process) -- bump with tools/editor-bridge/next-revision.ps1 and retry.")
    if outcome == OUT_ARM_REFUSED:
        return "The packet sink refused to arm (see the reply); nothing can be captured."
    if outcome == OUT_ENABLE_REFUSED:
        return "The native 3001 enable was refused; no log frames will be forwarded."
    if outcome == OUT_GRAPH_NOT_SELECTED:
        return ("The enable succeeded but the requested graph is NOT in the returned "
                "selection -- the click would capture nothing. Do not click.")
    if outcome == OUT_CALL_UNCERTAIN:
        return ("A dispatch timed out; a timeout is NOT proof of no effect. Re-run against a "
                "fresh scope.")
    return "No log-observer-evidence document (or no runLogSample field). Nothing to read."


# ---------------------------------------------------------------------------
# Timing arithmetic (pure): arm -> poll ... -> stop
# ---------------------------------------------------------------------------
def plan_poll_offsets(window: float, interval: float) -> list[float]:
    """Seconds after the arm at which to read back, the last one exactly at ``window``.

    Mirrors the runbook's shape -- read immediately, then every ``interval`` -- and always
    terminates with a poll at the lease edge so the buffer is read once more after the
    observer's own auto-stop (the counters and sample survive the stop).
    """
    if isinstance(window, bool) or not isinstance(window, (int, float)) or window <= 0:
        raise ValueError("WINDOW_INVALID:" + str(window))
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("INTERVAL_INVALID:" + str(interval))
    offsets = [0.0]
    k = 1
    while k * interval < window:
        offsets.append(round(k * interval, 9))
        k += 1
    if offsets[-1] != float(window):
        offsets.append(float(window))
    return offsets


def validate_window(window, interval, lease: float = OBSERVER_LEASE_SECONDS) -> dict:
    if isinstance(window, bool) or not isinstance(window, (int, float)):
        raise ValueError("WINDOW_INVALID:" + str(window))
    if window <= 0 or window > lease:
        raise ValueError(f"WINDOW_OUT_OF_RANGE:{window}:lease={lease}")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("INTERVAL_INVALID:" + str(interval))
    if interval > window:
        raise ValueError("INTERVAL_ABOVE_WINDOW:" + str(interval))
    return {"window": float(window), "interval": float(interval)}


def evidence_response_path(root: Path, run_id: str) -> Path:
    """Where call-bridge.ps1 writes this op's reply (call-bridge.ps1:99). Re-checkable."""
    return root / RUNS_REL / run_id / (OP_EVIDENCE + "-response.json")


# ===========================================================================
# MULTI-CHANNEL CAPTURE (2026-10-11; SEMANTICS FIXED 2026-10-12)
# ---------------------------------------------------------------------------
# One human click is scarce, so ONE run records every read-only observable that is
# (a) readable, (b) non-constant and (c) compatible with the 120 s window
# (``.runtime/scratch/CAPTURE-MATRIX.md``). Each observable is a *channel* with its own
# timestamped sampler.
#
# THE RULE THIS TABLE MUST ENCODE (it did not, until 2026-10-12):
#   ONLY ``log-evidence`` moves IFF OUR graph ran. Every other channel moves for reasons
#   of its OWN -- the observer's lifecycle, a growing keepalive count, a save, a scene
#   edit -- and is SUPPORTING CONTEXT, not evidence. The old table printed a bare
#   ``CHANGED`` for all of them, which was read as "our graph ran" when it proved
#   nothing. An adversary refuted exactly that on the 2026-10-11 run: ``observer-liveness``
#   said CHANGED in a run where NOTHING ran (its counters climb with the sink's own
#   lifecycle), and ``packet-kinds`` said CHANGED merely because a keepalive count grew
#   (``{0:9}`` -> ``{0:120}``).
#
# So a channel carries a ROLE, and the role decides the VERDICT VOCABULARY -- structural,
# not a footnote:
#
#   ROLE_DIAGNOSTIC  its value is a function of OUR graph's own output. It may say
#                    CHANGED / UNCHANGED / UNREADABLE. Today: ``log-evidence`` alone.
#   ROLE_CONTEXT     supporting context. It may NEVER print the word CHANGED: its
#                    movement verdicts are MOVED / STILL / UNREADABLE, and MOVED means
#                    only "this value moved for SOME reason" -- never "our graph ran".
#
# A context channel is also compared on a MEANING KEY, not its raw value, so a growth
# that is pure transport noise cannot move it: ``packet-kinds`` keys on the SET of packet
# IDs seen (a keepalive count climbing 9 -> 120 is not scene traffic), and
# ``observer-liveness`` keys on the sink's ATTACH bit alone (its counters climb with no
# click at all). The RAW values are still captured in full -- only the comparison key and
# the printed verdict changed.
# ===========================================================================
ROLE_DIAGNOSTIC = "diagnostic"   # its movement is a function of OUR graph's output
ROLE_CONTEXT = "context"         # supporting context; movement is NEVER proof of a run

VERDICT_CHANGED = "CHANGED"       # diagnostic: the value we track moved
VERDICT_UNCHANGED = "UNCHANGED"   # diagnostic: the value we track never moved
VERDICT_MOVED = "MOVED"           # context: the value moved (NOT evidence of a run)
VERDICT_STILL = "STILL"           # context: the value never moved (NOT evidence of none)
VERDICT_UNREADABLE = "UNREADABLE"  # < 2 successful reads: no comparison possible

#: The word a CONTEXT channel is allowed to say in place of each raw movement verdict.
#: It must never be CHANGED: that word is reserved for the one diagnostic channel.
_CONTEXT_VERDICT = {VERDICT_CHANGED: VERDICT_MOVED, VERDICT_UNCHANGED: VERDICT_STILL}

#: Offline description of every channel: (name, how read, what it shows, diagnostic?).
#: ``diagnostic`` is the 4th field; it is True for exactly one channel (``log-evidence``).
CHANNEL_REGISTRY = (
    ("log-evidence", "bridge call log-observer-evidence",
     "runLogSample rows = the graph's printed strings", True),
    ("packet-kinds", "same evidence doc, .packetKinds",
     "which packet ids were seen (a 1022 => the level was entered)", False),
    ("observer-liveness", "same evidence doc, .active (the sink counters are context only)",
     "the read-only sink was attached", False),
    ("gil-hash", "filesystem read (no helper)",
     "sha256 of every live level .gil (a SAVE artifact)", False),
    ("native-entities", "native-scene inspect via discover_current_level --queue-dir",
     "levelId + entity count (read-only native)", False),
)

#: What each channel's movement verdict MEANS, and what it does NOT (per the task: every
#: channel in the table must say both, and the table prints them so a reader cannot take a
#: context MOVED for a diagnostic CHANGED). Keyed by channel name.
CHANNEL_SEMANTICS = {
    "log-evidence": {
        "means": "OUR graph's printed strings appeared -- the ONLY execution signal here",
        "not_means": "the level was entered, a save happened, or any other graph ran",
    },
    "packet-kinds": {
        "means": "a packet ID was seen that was not seen before (counts are ignored)",
        "not_means": "our graph ran -- a keepalive count climbing 9 -> 120 is transport, not scene traffic",
    },
    "observer-liveness": {
        "means": "the read-only sink's ATTACH state (active) changed",
        "not_means": "our graph ran -- the sink's own counters climb with NO click at all",
    },
    "gil-hash": {
        "means": "a level .gil on disk changed bytes (a SAVE happened)",
        "not_means": "our graph ran -- the editor never persists a run, so this stays flat",
    },
    "native-entities": {
        "means": "the live level's id or entity count changed (a scene edit)",
        "not_means": "our graph ran -- an unrun graph leaves the scene identical",
    },
}


def diagnostic_channels() -> tuple:
    """The channels whose movement is a function of OUR graph's output (today: one)."""
    return tuple(name for name, *_rest, diag in CHANNEL_REGISTRY if diag)


def channel_verdict(samples, key=None) -> str:
    """Three-valued movement over one channel's samples: CHANGED / UNCHANGED / UNREADABLE.

    Describes MOVEMENT, never meaning: whether that movement is *diagnostic* is a property
    of the channel's ROLE, applied by ``Sampler.report_verdict``. ``key`` (optional)
    projects each sample's captured ``value`` to the thing whose movement is MEANINGFUL for
    this channel -- so pure transport noise (a keepalive count) cannot register as movement.
    The default key is the identity, i.e. the raw value.
    """
    good = [s for s in samples if isinstance(s, dict) and s.get("ok") is True]
    if len(good) < 2:
        return VERDICT_UNREADABLE
    project = key or (lambda value: value)
    first = project(good[0].get("value"))
    for sample in good[1:]:
        if project(sample.get("value")) != first:
            return VERDICT_CHANGED
    return VERDICT_UNCHANGED


def count_good(samples) -> int:
    return sum(1 for s in samples if isinstance(s, dict) and s.get("ok") is True)


def first_change_offset(samples, key=None):
    """Offset (s after arm) of the first read whose MEANING KEY differs from the first."""
    good = [s for s in samples if isinstance(s, dict) and s.get("ok") is True]
    if len(good) < 2:
        return None
    project = key or (lambda value: value)
    first = project(good[0].get("value"))
    for sample in good[1:]:
        if project(sample.get("value")) != first:
            return sample.get("offset")
    return None


# --- value fingerprints (pure; each returns None when the field is NOT readable) -----
def _is_evidence_doc(evidence) -> bool:
    return isinstance(evidence, dict) and evidence.get("ok") is True


def value_log_rows(evidence):
    """The graph's printed strings: {graph, text} rows. None if the sample is unusable."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get("runLogSample"), dict):
        return None
    return tuple(sorted((r["graph"], r["text"]) for r in text_rows(evidence)))


def value_packet_kinds(evidence):
    """Packet-id histogram. None when the document carries no packetKinds dict."""
    if not isinstance(evidence, dict):
        return None
    kinds = evidence.get("packetKinds")
    if not isinstance(kinds, dict):
        return None
    try:
        return tuple(sorted((int(k), int(v)) for k, v in kinds.items()))
    except (TypeError, ValueError):
        return None


def value_observer_liveness(evidence):
    """(active, observedPackets, observedLogPackets): is the sink attached and seeing traffic."""
    if not _is_evidence_doc(evidence):
        return None
    return (bool(evidence.get("active")), evidence.get("observedPackets"),
            evidence.get("observedLogPackets"))


# --- meaning keys: WHAT movement is allowed to count as informative --------------------
# A context channel's raw value often moves for reasons of its own. The key below projects
# the raw value down to the one part whose movement is meaningful, so noise cannot register.
#: Packet ids that are pure transport liveness and grow with the OBSERVER's own lifetime,
#: not with anything the graph did. MEASURED 2026-10-11: id 0 is a keepalive whose count
#: climbed ``{0:9}`` -> ``{0:120}`` with nobody clicking -- the defect this key closes.
KEEPALIVE_PACKET_IDS = frozenset({0})


def packet_kinds_key(value):
    """The SET of non-keepalive packet ids present. Counts are transport and are dropped.

    A keepalive-only mix (``{0:9}`` then ``{0:120}``, or ``{}`` then ``{0:N}``) maps to the
    same key, so it can never read as scene traffic. A genuinely new id (say 1022) moves it.
    """
    if value is None:
        return None
    return tuple(k for k, _count in value if k not in KEEPALIVE_PACKET_IDS)


def observer_liveness_key(value):
    """Only the sink's ATTACH bit. The counters are the sink's OWN lifecycle, not a signal."""
    if value is None:
        return None
    return value[0]


def native_entities_key(value):
    """(levelId, entity count) -- the scene fact. The per-read ``helperReplyOk`` is dropped."""
    if value is None:
        return None
    return (value[0], value[1])


def _sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gil_save_root():
    """The one ``BeyondLocal`` root under LocalLow\\miHoYo (READ-ONLY; never written)."""
    mihoyo = Path.home() / "AppData/LocalLow/miHoYo"
    if not mihoyo.is_dir():
        return None
    for sub in sorted((p for p in mihoyo.iterdir() if p.is_dir()), key=lambda p: p.name):
        candidate = sub / "BeyondLocal"
        if candidate.is_dir():
            return candidate
    return None


def value_gil_state(save_root):
    """Fingerprint of every live level ``.gil``: (relative name, byteSize, sha256).

    ``None`` when the root is absent/unreadable (the channel is then UNREADABLE, never a
    fabricated empty). An empty tuple means the root exists but holds no level .gil.
    """
    root = Path(save_root)
    if not root.is_dir():
        return None
    out = []
    for uid in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        level_dir = uid / "Beyond_Local_Save_Level"
        if not level_dir.is_dir():
            continue
        for gil in sorted(level_dir.rglob("*.gil"), key=lambda p: str(p)):
            try:
                out.append((str(gil.relative_to(root)), gil.stat().st_size, _sha256_file(gil)))
            except OSError:
                continue
    return tuple(out)


# --- renderers (one-line, human-readable "what it showed") --------------------------
def _default_render(value, limit=70):
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def render_log_rows(value):
    if not value:
        return "0 printed rows"
    texts = sorted({t for _g, t in value})
    return f"{len(value)} row(s): " + ", ".join(texts[:4])


def render_packet_kinds(value):
    if not value:
        return "no packets seen"
    shown = ", ".join(f"{k}:{c}" for k, c in value[:8])
    return "{" + shown + ("…" if len(value) > 8 else "") + "}"


def render_liveness(value):
    return f"active={value[0]} observedPackets={value[1]} logPackets={value[2]}"


def render_gil(value):
    if not value:
        return "0 .gil files"
    return f"{len(value)} file(s), {sum(sz for _n, sz, _h in value)} B total"


def render_native(value):
    return f"levelId={value[0]} entities={value[1]} helperReplyOk={value[2]}"


# --- samplers (all read-only; a read that fails records ok=False, never a fake success)
class Sampler:
    """One read-only observable, sampled over the window. Pure w.r.t. its reader.

    ``diagnostic`` decides the ROLE: only a diagnostic channel may say CHANGED. ``key``
    projects a captured value down to the part whose movement is meaningful for this
    channel, so transport noise cannot move a context channel (see the module header).
    """

    def __init__(self, name, describe, render=_default_render, decisive=False, key=None):
        self.name = name
        self.describe = describe
        self.render = render
        self.decisive = decisive
        self.key = key
        self.samples: list[dict] = []

    @property
    def role(self) -> str:
        return ROLE_DIAGNOSTIC if self.decisive else ROLE_CONTEXT

    def _record(self, offset, ok, value, note=""):
        self.samples.append({"offset": offset, "ok": bool(ok), "value": value, "note": note})

    def observe(self, offset, ctx):  # pragma: no cover - abstract
        raise NotImplementedError

    def verdict(self) -> str:
        """The RAW movement verdict, key-projected: CHANGED / UNCHANGED / UNREADABLE.

        Note this is NOT role-aware; it is the movement of the channel's meaning key. Use
        ``report_verdict`` for the string that must be PRINTED.
        """
        return channel_verdict(self.samples, self.key)

    def report_verdict(self) -> str:
        """The verdict as it must be printed, per ROLE.

        A context channel must never print a bare CHANGED -- its movement is not evidence
        that OUR graph ran -- so CHANGED/UNCHANGED become MOVED/STILL. Only a diagnostic
        channel keeps the CHANGED/UNCHANGED vocabulary.
        """
        raw = self.verdict()
        if self.decisive:
            return raw
        return _CONTEXT_VERDICT.get(raw, raw)

    def summary(self) -> str:
        good = [s for s in self.samples if s.get("ok") is True]
        if not self.samples:
            return "not sampled"
        if not good:
            notes = [s.get("note") for s in self.samples if s.get("note")]
            if not notes:
                return "no successful read"
            # Two reads can fail for two DIFFERENT reasons (measured: one gate rejection at
            # T+0 and one pre-flight image lock at T+110). Reporting only the last would hide
            # the first, so every distinct reason is counted and the earlier one is named.
            distinct = list(dict.fromkeys(notes))
            if len(distinct) > 1:
                return (f"no successful read ({len(distinct)} distinct reasons): {notes[-1]}"
                        f" | earlier: {distinct[0]}")
            return f"no successful read: {notes[-1]}"
        verdict = self.verdict()
        last = self.render(good[-1]["value"])
        if verdict == VERDICT_CHANGED:
            offset = first_change_offset(self.samples, self.key)
            return (f"changed at T+{offset:.0f}s | before: {self.render(good[0]['value'])} "
                    f"| after: {last}")
        if verdict == VERDICT_UNCHANGED:
            if channel_verdict(self.samples) == VERDICT_CHANGED:
                # the raw value moved but this channel's meaning key did not: the movement
                # is transport noise (a growing keepalive count, the sink's own counters),
                # NOT something the graph did. Say so instead of the lie "identical".
                return (f"{last} ({len(good)} reads; the raw value moved but the meaning key "
                        f"did not -- transport/observer noise, not graph evidence)")
            return f"{last} ({len(good)} reads, identical)"
        return f"single read ({len(good)}) — no movement test: {last}"


class EvidenceChannel(Sampler):
    """One field out of the log-observer-evidence document (free: the same bridge call)."""

    def __init__(self, name, extract, describe, render=_default_render, decisive=False,
                 key=None):
        super().__init__(name, describe, render, decisive, key)
        self.extract = extract

    def observe(self, offset, ctx):
        value = self.extract((ctx or {}).get("evidence"))
        if value is None:
            self._record(offset, False, None, "field absent from evidence document")
        else:
            self._record(offset, True, value)


class FilesystemChannel(Sampler):
    """A fingerprint read straight off disk -- no helper, no dispatch."""

    def __init__(self, name, root, reader, describe, render=_default_render, key=None):
        super().__init__(name, describe, render, decisive=False, key=key)
        self.root = root
        self.reader = reader

    def observe(self, offset, ctx):
        value = self.reader(self.root) if self.root else None
        if value is None:
            self._record(offset, False, None, "no readable root on disk")
        else:
            self._record(offset, True, value)


class NativeChannel(Sampler):
    """A native-scene read (target YuanShen.exe) at budgeted offsets only.

    The elevated runner serialises the queue and one native read costs 5-8 s, so this is
    spent at most twice per window (``schedule``), never polled.
    """

    def __init__(self, name, reader, schedule, describe, render=_default_render, key=None):
        super().__init__(name, describe, render, decisive=False, key=key)
        self.reader = reader
        self.schedule = list(schedule)
        self._next = 0

    def observe(self, offset, ctx):
        while self._next < len(self.schedule) and self.schedule[self._next] <= offset + 1e-6:
            self._next += 1
            try:
                ok, value, note = self.reader()
            except Exception as ex:  # a failed read is UNREADABLE, never a fake success
                ok, value, note = False, None, f"{type(ex).__name__}: {ex}"
            self._record(offset, ok, value, note)


# --- scheduling + native transport ---------------------------------------------------
def pick_native_offsets(offsets, window, margin=10.0):
    """Poll offsets at which to spend a native read: the first, and the latest that still
    leaves ``margin`` seconds before the lease edge. Deduped (a tiny window -> one)."""
    offsets = list(offsets or [])
    if not offsets:
        return []
    chosen = [offsets[0]]
    edge = float(window) - float(margin)
    late = [o for o in offsets if o <= edge + 1e-9 and o > chosen[0]]
    if late:
        chosen.append(late[-1])
    return chosen


# --- the pre-flight disk lock (why this channel can fail WITHOUT reading the level) ---
#: THE ONE fault this channel can report that is NOT about the level at all.
#:
#: ``discover_current_level.py`` re-validates the pinned readonly profile against the
#: ON-DISK game image *before* it enqueues anything: ``verify_disk`` opens
#: ``C:\\Games\\Genshin Impact Game\\YuanShen.exe`` (``native_profiles.py:104-119`` --
#: file size, PE headers, the sha256 of the whole image, the four anchor byte patterns)
#: and ``validate_session`` re-resolves that same path (``native_profiles.py:150``
#: ``Path(...).resolve()``). While another process holds the image without a read share,
#: Windows fails that open with ERROR_SHARING_VIOLATION, which Python reports as
#: ``PermissionError: [Errno 13] Permission denied: '<...>\\YuanShen.exe'``.
#:
#: MEASURED 2026-10-11: the SAME probe succeeds while ``YuanShen.exe`` is running at the
#: desktop (pid 104760, verified by this session), so the lock is a property of the
#: MOMENT, not of the file. The two failing reads of the recorded playtest run sit
#: ``T+0`` and ``T+110`` apart, so a lock can outlive the whole 120 s window.
#:
#: It is a PRE-DISPATCH fault: in ``discover_via_queue`` both open sites (``:637``
#: ``verify_disk``, ``:651`` ``validate_session``) precede ``queue_send`` (``:656``).
#: Retrying therefore costs a few hundred milliseconds and can NEVER spend a second
#: native read.
_PREFLIGHT_IMAGE_LOCK = re.compile(
    r"(?i)(permission denied|access is denied|winerror 32|sharing violation)"
    r"[^\n]*\.exe'")
#: Total attempts for the pre-flight lock only (1 = no retry). Bounded on purpose: the
#: channel gets two reads per window and each native read costs 5-8 s of serialized
#: queue, so this must stay cheap.
PREFLIGHT_ATTEMPTS = 3
PREFLIGHT_RETRY_DELAY = 0.5


def is_preflight_image_lock(reply) -> bool:
    """A driver-level fault whose message is the on-disk game image lock.

    Deliberately narrow. ``failedAt`` is produced ONLY by ``discover_current_level.main``'s
    own exception handler, so this can never match a gate rejection (which carries
    ``reasons`` + ``run``): those are verdicts about a read that DID happen, and
    re-dispatching one would spend a second native read and could double-report a run.
    """
    if not isinstance(reply, dict) or "failedAt" not in reply:
        return False
    return bool(_PREFLIGHT_IMAGE_LOCK.search(str(reply.get("error") or "")))


def native_failure_note(reply, limit=300) -> str:
    """The note for a failed native reply: WHERE and WHY, never a bare exception.

    ``discover_current_level.main`` already reports the innermost frames
    (``failedAt``/``failedSource``) precisely so a fault can be placed in the chain; the
    channel must not re-throw that away and print a naked ``PermissionError`` that cannot
    be told apart from "the level was unreadable".
    """
    if not isinstance(reply, dict):
        return "reply-not-a-document"
    text = str(reply.get("error") or reply.get("reasons") or "ok=False")
    head = []
    if is_preflight_image_lock(reply):
        head.append("PREFLIGHT_GAME_IMAGE_LOCK[driver could not re-hash the pinned game "
                    "image on disk; nothing was dispatched, so this says NOTHING about "
                    "the level]")
    frames = reply.get("failedAt")
    if isinstance(frames, list) and frames:
        ends = [str(frames[0])] if len(frames) == 1 else [str(frames[0]), str(frames[-1])]
        head.append("at " + " <- ".join(ends))
    tries = reply.get("preflightAttempts")
    if isinstance(tries, int) and tries > 1:
        head.append(f"attempts={tries}")
    note = ((" | ".join(head) + ": ") if head else "") + text
    return note[:limit]


def native_inspect(root, output_root, *, queue_rel=QUEUE_REL, timeout=20.0,
                   attempts=PREFLIGHT_ATTEMPTS, retry_delay=PREFLIGHT_RETRY_DELAY):
    """One read-only native read through the resident helper (never UAC, never a write).

    Delegates to the pinned, in-tree driver ``discover_current_level.py --queue-dir``,
    which refuses rather than falling back to a UAC launch and itself re-validates the
    helper's heartbeat/capability/identity before enqueueing.

    A PRE-DISPATCH failure -- the driver could not re-hash the pinned game image on disk
    (``_PREFLIGHT_IMAGE_LOCK``) -- is retried up to ``attempts`` times with ``retry_delay``
    between tries, and the number of tries taken is recorded on the reply as
    ``preflightAttempts`` so the channel can say a retry happened rather than downgrading
    silently. EVERY other outcome, in particular any fault raised after a native read was
    dispatched, is returned on the first try, unretried.
    """
    reply = None
    used = 0
    for used in range(1, max(1, int(attempts)) + 1):
        reply = _inspect_once(root, output_root, queue_rel=queue_rel, timeout=timeout)
        if used >= attempts or not is_preflight_image_lock(reply):
            break
        time.sleep(float(retry_delay))
    if isinstance(reply, dict) and reply.get("preflightAttempts") is None:
        reply = dict(reply, preflightAttempts=used)
    return reply


def _inspect_once(root, output_root, *, queue_rel=QUEUE_REL, timeout=20.0):
    """Exactly one driver invocation. Raises on a missing driver or non-JSON output."""
    script = root / "tools/game-executor/discover_current_level.py"
    if not script.is_file():
        raise RuntimeError("NATIVE_INSPECT_DRIVER_MISSING")
    cmd = [sys.executable, "-B", str(script), "--queue-dir", queue_rel,
           "--output-root", str(output_root), "--queue-timeout", str(timeout)]
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", cwd=str(root),
                          timeout=float(timeout) + 30.0)
    text = (proc.stdout or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("NATIVE_INSPECT_NON_JSON:" + ((text or proc.stderr or "")[:200]))


def read_native(reply_fn):
    """Wrap a native reply into a sampler's ``(ok, value, note)`` shape."""
    def _read():
        reply = reply_fn()
        if not isinstance(reply, dict):
            return False, (None, None, None), "reply-not-a-document"
        value = (reply.get("levelId"), reply.get("entities"), reply.get("helperReplyOk"))
        ok = reply.get("ok") is True and isinstance(reply.get("levelId"), int)
        return ok, value, ("" if ok else native_failure_note(reply))
    return _read


def build_samplers(root, run_id, cfg, *, native=True, gil_root="auto", native_timeout=20.0,
                   native_reader=None):
    """Every channel that is readable, non-constant and compatible with the window."""
    samplers = [
        EvidenceChannel("log-evidence", value_log_rows,
                        "runLogSample rows (the graph's printed strings)",
                        render=render_log_rows, decisive=True),
        EvidenceChannel("packet-kinds", value_packet_kinds,
                        "which packet ids were seen (a 1022 => the level was entered)",
                        render=render_packet_kinds, key=packet_kinds_key),
        EvidenceChannel("observer-liveness", value_observer_liveness,
                        "the read-only sink was attached",
                        render=render_liveness, key=observer_liveness_key),
    ]
    if gil_root is not None:
        save_root = gil_save_root() if gil_root == "auto" else gil_root
        samplers.append(FilesystemChannel("gil-hash", save_root, value_gil_state,
                                          "sha256 of every live level .gil (a SAVE artifact)",
                                          render=render_gil))
    if native:
        offsets = pick_native_offsets(plan_poll_offsets(cfg["window"], cfg["interval"]),
                                      cfg["window"])
        if native_reader is None:
            out_root = root / RUNS_REL / run_id / "native-inspect"

            def native_reader():
                return native_inspect(root, out_root, timeout=native_timeout)
        samplers.append(NativeChannel("native-entities", read_native(native_reader), offsets,
                                      "levelId + entity count (read-only native)",
                                      render=render_native, key=native_entities_key))
    return samplers


def channel_role(ch) -> str:
    """The ROLE of a channel row: explicit ``role``, else derived from the ``decisive`` flag."""
    role = ch.get("role")
    if role in (ROLE_DIAGNOSTIC, ROLE_CONTEXT):
        return role
    return ROLE_DIAGNOSTIC if ch.get("decisive") else ROLE_CONTEXT


def _channel_row(sampler) -> dict:
    return {
        "name": sampler.name,
        "describe": sampler.describe,
        "role": sampler.role,
        "decisive": sampler.decisive,
        # ``verdict`` is the PRINTED (role-aware) verdict; ``keyVerdict`` is the movement of
        # the MEANING KEY before the role vocabulary is applied (they differ only for a
        # context channel: CHANGED->MOVED, UNCHANGED->STILL); ``valueMoved`` is whether the
        # RAW captured value moved at all -- True while ``keyVerdict`` is UNCHANGED is the
        # signature of transport/observer noise, NOT graph evidence.
        "verdict": sampler.report_verdict(),
        "keyVerdict": sampler.verdict(),
        "valueMoved": channel_verdict(sampler.samples) == VERDICT_CHANGED,
        "reads": len(sampler.samples),
        "readsOk": count_good(sampler.samples),
        "summary": sampler.summary(),
        "samples": sampler.samples,
    }


def diagnostic_verdict(channels):
    """The printed verdict of the one diagnostic channel, or None if it was not built."""
    for ch in channels or []:
        if channel_role(ch) == ROLE_DIAGNOSTIC:
            return ch.get("verdict")
    return None


def print_channel_registry():
    """Offline: the channel surface this supervisor attaches, AND what each verdict means."""
    print("CHANNELS (one playtest run records all that are readable + non-constant "
          "+ window-compatible)")
    width = max(len(name) for name, *_ in CHANNEL_REGISTRY)
    for name, how, shows, diag in CHANNEL_REGISTRY:
        role = ROLE_DIAGNOSTIC if diag else ROLE_CONTEXT
        print(f"  {name:<{width}}  [{role:<10}] {how}")
        print(f"  {'':<{width}}    shows: {shows}")
        sem = CHANNEL_SEMANTICS.get(name)
        if sem:
            word = "CHANGED" if diag else "MOVED"
            print(f"  {'':<{width}}    {word} means: {sem['means']}")
            print(f"  {'':<{width}}    it does NOT mean: {sem['not_means']}")
    print("  ONLY the diagnostic channel (log-evidence) can say CHANGED. A context channel "
          "says MOVED/STILL, which is supporting context and NEVER proof our graph ran.")


def channel_table_lines(channels) -> list[str]:
    """The single all-channel table (what was captured, what it showed, verdict).

    The ROLE column is structural: a reader sees at a glance that at most one row is
    diagnostic, and every other row's movement is context.
    """
    if not channels:
        return []
    rows = [("role", "channel", "verdict", "reads", "what it showed")]
    for ch in channels:
        role = channel_role(ch)
        star = "* " if role == ROLE_DIAGNOSTIC else "  "
        rows.append((role, star + str(ch.get("name", "?")), str(ch.get("verdict", "?")),
                     f"{ch.get('readsOk', 0)}/{ch.get('reads', 0)}", str(ch.get("summary", ""))))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    out = ["CHANNEL CAPTURE TABLE  —  ONLY the diagnostic row can say CHANGED; a context "
           "row's MOVED is context, never proof the graph ran"]
    for index, row in enumerate(rows):
        out.append(f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:<{widths[2]}}  "
                   f"{row[3]:>5}  {row[4]}")
        if index == 0:
            out.append("-" * min(140, sum(widths) + 16))
    return out


def channel_semantics_lines(channels) -> list[str]:
    """One line per attached channel: what its movement verdict means and does NOT mean."""
    names = {ch.get("name") for ch in (channels or [])}
    out = []
    for name, sem in CHANNEL_SEMANTICS.items():
        if name not in names:
            continue
        diag = name in diagnostic_channels()
        word = "CHANGED" if diag else "MOVED/STILL"
        out.append(f"  {name}: {word} means {sem['means']} — it does NOT mean "
                   f"{sem['not_means']}")
    return out


# ---------------------------------------------------------------------------
# Selection gate
# ---------------------------------------------------------------------------
def selection_contains(enable, name: str | None, graph_id: int | None) -> bool:
    """Is the requested graph in the enable reply's returned selection?"""
    selection = enable.get("selection") if isinstance(enable, dict) else None
    graphs = selection.get("Graphs") if isinstance(selection, dict) else None
    if not isinstance(graphs, list) or not graphs:
        return False
    for graph in graphs:
        if not isinstance(graph, dict):
            continue
        if graph_id is not None and graph.get("id") == graph_id:
            return True
        if name and graph.get("name") == name:
            return True
    return False


def selection_summary(enable) -> str:
    selection = enable.get("selection") if isinstance(enable, dict) else None
    graphs = selection.get("Graphs") if isinstance(selection, dict) else None
    if not isinstance(graphs, list):
        return "(no selection returned)"
    parts = []
    for graph in graphs:
        if isinstance(graph, dict):
            parts.append(f"{graph.get('name')}={graph.get('id')}({graph.get('nodeCount')}n)")
    return ", ".join(parts) or "(empty selection)"


def _scope_gone(reply) -> bool:
    return isinstance(reply, dict) and "SCOPE_EXPIRED" in str(reply.get("error", ""))


# ---------------------------------------------------------------------------
# Live session: every machine action funnels through here.
# ---------------------------------------------------------------------------
class LiveSession:
    """Thin shell over elevated-request.py (the only unprivileged transport)."""

    def __init__(self, root: Path, run_id: str = "", target_pid: int | None = None,
                 timeout: float = 60.0, log=None):
        self.root = root
        self.run_id = run_id or ""
        self.target_pid = target_pid
        self.timeout = timeout
        self.seq = 0
        self._req = root / "tools/editor-bridge/elevated-request.py"
        self._log = log or (lambda _m: None)

    def _dispatch(self, argv: list[str]) -> dict:
        cmd = [sys.executable, str(self._req), "--queue-dir", QUEUE_REL] + argv
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", cwd=str(self.root))
        text = (proc.stdout or "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError(f"CALL_NON_JSON:{(text or proc.stderr or '')[:300]}")

    def load(self) -> dict:
        if not isinstance(self.target_pid, int) or self.target_pid <= 0:
            raise RuntimeError("TARGET_PID_REQUIRED: pass --target-pid")
        self._log(f"[load] target pid {self.target_pid}")
        reply = self._dispatch(["load", "--target-pid", str(self.target_pid)])
        if reply.get("accepted") is True and reply.get("runId"):
            self.run_id = str(reply["runId"])
        return reply

    def call(self, op: str) -> dict:
        if not self.run_id:
            raise RuntimeError("NO_LIVE_RUN: run the load step first")
        self.seq += 1
        rid = _pl.request_id_for(op, self.run_id, self.seq)
        self._log(f"[call {self.seq:02d}] {op}")
        return self._dispatch(["call", "--op", op, "--run-id", self.run_id,
                               "--request-id", rid, "--timeout", str(int(self.timeout))])


# ---------------------------------------------------------------------------
# Orchestration (pure w.r.t. the session + clock, so it is testable offline).
# ---------------------------------------------------------------------------
def orchestrate(session, cfg: dict, *, on_banner=None, on_poll=None,
                sleep=time.sleep, now=time.monotonic, samplers_for=None) -> dict:
    """load -> arm -> enable -> banner -> poll(window) -> stop. Returns one result dict.

    ``samplers_for(run_id)`` (optional) yields the read-only channel samplers; they are
    observed at each poll offset so every channel rides the SAME window. A channel that
    cannot be read records ``ok=False``; it never fabricates a success.

    ``cfg["profile"]`` (optional; ``PROFILE_DEMO`` when absent) picks the graph's string set
    and thus the classifier -- a config without a profile keeps the original demo semantics,
    so every caller written before WAVE-29AT behaves exactly as it did.
    """
    profile = cfg.get("profile") or PROFILE_DEMO
    result: dict = {
        "graphName": cfg.get("graph_name"),
        "graphId": cfg.get("graph_id"),
        "profile": profile,
        "window": cfg["window"],
        "interval": cfg["interval"],
    }

    load = session.load()
    result["load"] = load
    if load.get("accepted") is not True:
        result["outcome"] = OUT_LOAD_REFUSED
        result["runId"] = session.run_id or None
        return result
    result["runId"] = session.run_id
    samplers = list(samplers_for(session.run_id)) if samplers_for is not None else []

    arm = session.call(OP_ARM)
    result["arm"] = arm
    if arm.get("ok") is not True or arm.get("active") is not True:
        result["outcome"] = OUT_ARM_REFUSED
        return result

    enable = session.call(OP_ENABLE)
    result["enable"] = enable
    if enable.get("ok") is not True:
        result["outcome"] = OUT_ENABLE_REFUSED
        return result
    if not selection_contains(enable, cfg.get("graph_name"), cfg.get("graph_id")):
        result["outcome"] = OUT_GRAPH_NOT_SELECTED
        result["selection"] = selection_summary(enable)
        return result
    result["selection"] = selection_summary(enable)

    if on_banner is not None:
        on_banner(cfg, session.run_id, enable)

    offsets = plan_poll_offsets(cfg["window"], cfg["interval"])
    arm_at = now()
    evidence: dict = {}
    failures = 0
    try:
        for index, offset in enumerate(offsets):
            wait = (arm_at + offset) - now()
            if wait > 0:
                sleep(wait)
            reply = session.call(OP_EVIDENCE)
            if reply.get("ok") is True:
                evidence = reply
            else:
                failures += 1
                if _scope_gone(reply):
                    break
            for sampler in samplers:
                sampler.observe(offset, {"evidence": evidence, "root": getattr(session, "root", None)})
            if on_poll is not None:
                on_poll(offset, reply)
    finally:
        stop = session.call(OP_STOP)
        result["stop"] = stop

    result["evidence"] = evidence
    result["pollFailures"] = failures
    result["outcome"] = classify_with_profile(profile, evidence)
    if profile == PROFILE_MODPROBE:
        result["moduleCapture"] = module_probe_capture(evidence)
        result["literals"] = result["moduleCapture"]["capturedOrder"]
    else:
        result["literals"] = captured_literals(evidence)
    if not evidence and failures:
        result["outcome"] = OUT_CALL_UNCERTAIN
    if samplers:
        result["channels"] = [_channel_row(s) for s in samplers]
    return result


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------
def _print_banner(cfg, run_id, enable, root: Path):
    path = evidence_response_path(root, run_id)
    target = cfg.get("graph_name") or cfg.get("graph_id") or "our live MW_* graphs"
    line = "=" * 78
    print(line, flush=True)
    print(
        f">>> CLICK NOW <<<  run={run_id}  window={cfg['window']:.0f}s  "
        f"— in BeyondEditor: 系统菜单 → 【试玩】→ (试玩设置) → 装扮展示 → 加载界面 → 进入关卡",
        flush=True)
    print(f"    HOW LONG: click any time in the next {cfg['window']:.0f}s; the tool is polling.",
        flush=True)
    print(f"    GRAPH-LOG FILTER (节点图筛选): NO TICK REQUIRED — the bridge just selected "
          f"{target} itself.", flush=True)
    print(f"      selection now: {selection_summary(enable)}", flush=True)
    print(f"      optional fallback ONLY if this run ends NO_LOG_TRAFFIC: 节点图筛选 → tick "
          f"{cfg.get('graph_name') or PROFILE_GRAPH_NAME.get(cfg.get('profile'), 'MW_API_DEMO_RUN2')}.",
          flush=True)
    expected = profile_expected_lines(cfg.get("profile"))
    print(f"    EXPECTED OUTPUT ({len(expected)} line(s), in order) — a capture is a PREFIX:",
          flush=True)
    for _i, _line in enumerate(expected):
        print(f"      {_i + 1}. {_line}", flush=True)
    print("    Do NOT click anything else in the world; stay in the playtest until this "
          "tool prints its timeline.", flush=True)
    print(f"    RAW EVIDENCE: {path}", flush=True)
    print(f"    RECHECK OFFLINE: python tools/editor-bridge/playtest_log.py render --evidence "
          f"\"{path}\"", flush=True)
    print(line, flush=True)


def _print_poll(offset, reply):
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        print(f"    [T+{offset:6.0f}s] (poll failed: {str(reply.get('error'))[:80]})", flush=True)
        return
    sample = reply.get("runLogSample") if isinstance(reply.get("runLogSample"), dict) else {}
    print(f"    [T+{offset:6.0f}s] active={reply.get('active')} "
          f"observedPackets={reply.get('observedPackets')} "
          f"observedLogPackets={reply.get('observedLogPackets')} "
          f"recordsSeen={sample.get('recordsSeen')}", flush=True)


def _print_result(result: dict, root: Path):
    run_id = result.get("runId") or "<none>"
    outcome = result.get("outcome", OUT_UNUSABLE)
    evidence = result.get("evidence")
    ev = evidence if isinstance(evidence, dict) else {}
    sample = ev.get("runLogSample") if isinstance(ev.get("runLogSample"), dict) else {}
    rows = text_rows(evidence)
    print("", flush=True)
    print(f"PLAYTEST ONE-CLICK - run {run_id}", flush=True)
    print(f"verdict: {outcome}", flush=True)
    print(f"  {outcome_explanation(outcome, evidence)}", flush=True)
    print(f"counters: observedPackets={ev.get('observedPackets')} "
          f"observedLogPackets={ev.get('observedLogPackets')} "
          f"recordsSeen={records_seen(evidence)} "
          f"sampleRows={len(sample.get('sample') or []) if isinstance(sample.get('sample'), list) else 0} "
          f"observerActive={ev.get('active')} pollFailures={result.get('pollFailures')}", flush=True)
    profile = result.get("profile", PROFILE_DEMO)
    if result.get("literals") is not None:
        lits = result["literals"]
    elif profile == PROFILE_MODPROBE:
        lits = module_probe_capture(evidence)["capturedOrder"]
    else:
        lits = captured_literals(evidence)
    label = "module lines captured" if profile == PROFILE_MODPROBE else "demo literals captured"
    print(f"{label}: {', '.join(lits) if lits else '(none)'}", flush=True)
    if rows:
        print("rows:", flush=True)
        for row in rows:
            print(f"  {row['utc']}  {row['graph']}  {row['text']}", flush=True)
    else:
        print("rows: (none)", flush=True)
    if profile == PROFILE_MODPROBE:
        cap = result.get("moduleCapture") or module_probe_capture(evidence)
        ran = ", ".join(cap["modulesRan"]) or "(none)"
        print("", flush=True)
        print("MODULE PROBE ATTRIBUTION (the chain is LINEAR, so a capture is a PREFIX):",
              flush=True)
        print(f"  lines captured : {len(cap['capturedOrder'])} of {len(MODPROBE_PRINTS)}",
              flush=True)
        print(f"  modules that RAN (their node executed): {ran}", flush=True)
        print(f"  first line MISSING (where the chain stopped): {cap['firstMissing'] or '(none)'}",
              flush=True)
        if cap["complete"]:
            print("  => the WHOLE chain ran: every module node executed.", flush=True)
        elif cap["capturedOrder"]:
            nxt = cap["firstMissing"] or "?"
            print(f"  => the chain aborted BEFORE {MODPROBE_TEXT_TO_MODULE.get(nxt, '?')} "
                  f"({nxt!r}).", flush=True)
        if cap["foreign"]:
            print(f"  foreign lines (NOT ours; attribute nothing): {cap['foreign']}", flush=True)
    if run_id not in (None, "<none>"):
        path = evidence_response_path(root, run_id)
        print(f"RAW EVIDENCE: {path}", flush=True)
        print(f"RECHECK OFFLINE: python tools/editor-bridge/playtest_log.py render --evidence "
              f"\"{path}\"", flush=True)
    channels = result.get("channels") or []
    table = channel_table_lines(channels)
    if table:
        print("", flush=True)
        for line in table:
            print(line, flush=True)
        diag = diagnostic_verdict(channels)
        print(f"  DIAGNOSTIC CHANNEL (the ONLY one that moves iff OUR graph ran): log-evidence "
              f"= {diag}; every other row is CONTEXT.", flush=True)
        for line in channel_semantics_lines(channels):
            print(line, flush=True)
        print("  (A diagnostic CHANGED says OUR graph emitted output. A context MOVED says "
              "only that that channel's value moved for SOME reason; STILL that it did not. "
              "UNREADABLE = fewer than 2 successful reads, so no movement test was possible.)",
              flush=True)
    print(f"exit: {exit_code_for(outcome)}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_target_pid(root: Path) -> int | None:
    """The pid the most recent bridge scope targets -- no process-name guessing."""
    runs = root / RUNS_REL
    if not runs.exists():
        return None
    best = None
    for settings in runs.glob("*/bridge-settings.json"):
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            pid = int(data["pid"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        stamp = settings.stat().st_mtime
        if best is None or stamp > best[0]:
            best = (stamp, pid)
    return best[1] if best else None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="playtest_one_click.py",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("channels", help="offline: list the observable channels and exit")
    run = sub.add_parser("run", help="load -> arm -> banner -> poll -> stop (the one run)")
    run.add_argument("--target-pid", type=int, default=None,
                     help="editor pid to load into; default = the newest scope's pid")
    run.add_argument("--expect", choices=(PROFILE_MODPROBE, PROFILE_DEMO),
                     default=PROFILE_MODPROBE,
                     help="WHICH graph's string set the click is for: 'modprobe' (default; "
                          "MW_API_MODPROBE, one printed line per module) or 'demo' "
                          "(MW_API_DEMO_RUN2 and its four branch literals)")
    run.add_argument("--graph-name", default=None,
                     help="graph the enable selection must contain; default = the --expect "
                          "profile's graph name ('' disables the gate)")
    run.add_argument("--graph-id", type=int, default=None,
                     help="graph id the enable selection must contain")
    run.add_argument("--window", type=float, default=OBSERVER_LEASE_SECONDS,
                     help="capture window in seconds (<= 120, the observer lease)")
    run.add_argument("--interval", type=float, default=5.0,
                     help="seconds between read-only read-backs")
    run.add_argument("--timeout", type=float, default=60.0, help="per-dispatch queue timeout")
    run.add_argument("--dry-run", action="store_true",
                     help="print the op plan and exit; dispatch nothing")
    run.add_argument("--no-native", action="store_true",
                     help="skip the native inspect sampler (no native dispatch at all)")
    run.add_argument("--no-gil", action="store_true",
                     help="skip the live .gil hash sampler")
    run.add_argument("--native-timeout", type=float, default=20.0,
                     help="queue timeout for each native inspect (seconds)")
    run.add_argument("--json", action="store_true", help="emit the result document as JSON")
    return ap


def main(argv=None) -> int:
    try:  # keep emitted graph text intact on a cp936 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    root = project_root()

    if args.cmd == "channels":
        print_channel_registry()
        return 0

    try:
        cfg = validate_window(args.window, args.interval)
    except ValueError as ex:
        raise SystemExit(str(ex))
    profile = args.expect
    cfg["profile"] = profile
    # ``''`` still DISABLES the gate (the pre-WAVE-29AT contract); only an ABSENT --graph-name
    # falls back to the profile's own graph.
    if args.graph_name is None:
        cfg["graph_name"] = PROFILE_GRAPH_NAME.get(profile, DEFAULT_GRAPH_NAME)
    else:
        cfg["graph_name"] = args.graph_name or None
    cfg["graph_id"] = args.graph_id

    native_enabled = not args.no_native
    gil_root = None if args.no_gil else "auto"

    if args.dry_run:
        offsets = plan_poll_offsets(cfg["window"], cfg["interval"])
        print(json.dumps({
            "plan": [OP_LOAD, OP_ARM, OP_ENABLE] + [OP_EVIDENCE] * len(offsets) + [OP_STOP],
            "pollOffsets": offsets,
            "window": cfg["window"],
            "interval": cfg["interval"],
            "profile": cfg["profile"],
            "graphName": cfg["graph_name"],
            "graphId": cfg["graph_id"],
            "expectedLines": list(profile_expected_lines(cfg["profile"])),
            "channels": [name for name, *_ in CHANNEL_REGISTRY
                         if (name != "native-entities" or native_enabled)
                         and (name != "gil-hash" or gil_root is not None)],
            "nativeOffsets": pick_native_offsets(offsets, cfg["window"]) if native_enabled else [],
        }, ensure_ascii=False, indent=2))
        return 0

    target_pid = args.target_pid if args.target_pid is not None else default_target_pid(root)
    if target_pid is None:
        raise SystemExit("TARGET_PID_REQUIRED: no bridge scope on disk; pass --target-pid")
    session = LiveSession(root, target_pid=target_pid, timeout=args.timeout)

    def on_banner(c: dict, run_id: str, enable):
        _print_banner(c, run_id, enable, root)

    def samplers_for(run_id):
        return build_samplers(root, run_id, cfg, native=native_enabled, gil_root=gil_root,
                              native_timeout=args.native_timeout)

    try:
        result = orchestrate(session, cfg, on_banner=on_banner, on_poll=_print_poll,
                             samplers_for=samplers_for)
    except RuntimeError as ex:
        print(f"verdict: {OUT_CALL_UNCERTAIN}\n  {ex}", flush=True)
        return 3

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        _print_result(result, root)
    return exit_code_for(result.get("outcome", OUT_UNUSABLE))


if __name__ == "__main__":
    raise SystemExit(main())
