#!/usr/bin/env python3
"""enable-own-graph-logging must select the graph THE CALLER NAMES -- never a stale course set.

WHY THIS FILE EXISTS

`ConfigureOwnGraphLogSelection` hard-required two graphs by exact stored name --
`MW_Platform_Calibration_20260916` and `MW_Route_Tiled_20260916`. Neither exists in the
live level any more, so the op refused every time with

    LOG_SELECTION_GRAPH_IDENTITY_NOT_UNIQUE:MW_Platform_Calibration_20260916:0

The trailing ``:0`` was the MATCH COUNT, not "not unique": the identity lookup found
NONE. (The refusal code lied about its own cause, which is why it is pinned here.)

The fix makes the identity come from the REQUEST: ``ids`` (the only extra field the
bridge queue can carry on a ``call``) and/or ``graphName``; failing both, every graph of
THIS PROJECT present in the LIVE level is selected, using the same ``MW_`` name-prefix
rule the bounded graph-delete already uses. No id is hardcoded, nothing is selected
silently, and every failure is a named refusal.

WHAT IS REAL vs SYNTHETIC HERE
------------------------------
* REAL, read as text: the Adapter, BridgeServer, call-bridge.ps1 and elevated-runner.ps1
  in this checkout.
* REAL, EXECUTED: ``Get-ValidatedCallArguments`` is lifted out of the runner with the
  PowerShell AST and run against untrusted queue bodies (part D). That is a BEHAVIOUR
  assertion, not a text scan.
* SYNTHETIC: nothing is dispatched. No queue, no helper, no editor, no game. The
  selection planner itself needs a live editor (a ``Resource`` wraps a live model), so
  its live behaviour is verified on the machine, not here.

Part D pins an HONEST LIMIT: the QUEUE path still cannot carry ``ids`` to this op,
because the runner's closed per-op schema is pinned. ``call-bridge.ps1`` forwards
``-Ids`` verbatim for ANY op, and it is directly invocable (probe-log-observer.ps1 does
exactly that), so the explicit-id path is reachable by calling call-bridge.ps1 directly.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_own_graph_log_selection
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "tools/editor-bridge/Adapter/GraphLogSelection.cs"
EDITOR_ADAPTER = ROOT / "tools/editor-bridge/Adapter/EditorAdapter.cs"
BRIDGE_SERVER = ROOT / "tools/editor-bridge/ManagedBridge/BridgeServer.cs"
CALL_BRIDGE = ROOT / "tools/editor-bridge/call-bridge.ps1"
RUNNER = ROOT / "tools/editor-bridge/elevated-runner.ps1"

OP = "enable-own-graph-logging"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class AdapterIdentityComesFromTheRequest(unittest.TestCase):
    """The selection identity is a parameter, and the stale set is gone as a REQUIREMENT."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(ADAPTER)

    def test_stale_course_names_are_no_longer_referenced(self) -> None:
        # The identifiers, not the words: the docstring may still narrate the old bug.
        self.assertNotIn("CalibrationGraphName", self.src)
        self.assertNotIn("TiledRouteName", self.src)
        self.assertNotIn("AuditGraphName", self.src)
        self.assertNotIn("PositionGraphName", self.src)
        self.assertNotIn("FinishGraphName", self.src)

    def test_the_category_hard_gate_is_gone(self) -> None:
        # category[2]==21001 was a second way to reject a live graph nobody knew about.
        self.assertNotIn("LogSelectionGraphCategory", self.src)
        self.assertNotIn("LOG_SELECTION_CATEGORY_MISMATCH", self.src)

    def test_identity_is_taken_from_the_request(self) -> None:
        # the reader lives here; the caller (EditorAdapter.cs) invokes it with the request.
        self.assertIn("OwnGraphLogSelectionRequest(JsonElement request)", self.src)
        self.assertIn("OwnGraphLogSelectionRequest(request)", _read(EDITOR_ADAPTER))
        self.assertIn("requestedIds", self.src)
        self.assertIn("requestedName", self.src)
        # the planner is what the caller passes the request-derived identity into.
        self.assertIn("PlanOwnGraphLogSelection(Resources(),requestedName,requestedIds)", self.src)

    def test_named_refusals_never_a_silent_selection(self) -> None:
        for code in (
            "LOG_SELECTION_GRAPH_NOT_FOUND_IN_LEVEL:",
            "LOG_SELECTION_GRAPH_NOT_FOUND:",
            "LOG_SELECTION_IDS_NOT_UNIQUE:",
            "LOG_SELECTION_UNKNOWN_OR_DUPLICATE_FIELD:",
            "LOG_SELECTION_ID_INVALID",
            "LOG_SELECTION_GRAPH_NAME_INVALID",
        ):
            self.assertIn(code, self.src, f"missing named refusal {code}")

    def test_live_fallback_uses_the_own_graph_prefix_not_a_pinned_id(self) -> None:
        self.assertIn('const string OwnGraphLogNamePrefix="MW_"', self.src)
        self.assertIn("StartsWith(OwnGraphLogNamePrefix", self.src)
        # (a) the live level is what is read, (b) no live/level graph id is baked in.
        self.assertIn("Kind==9", self.src)
        self.assertNotIn("1073741831", self.src)

    def test_the_plan_is_reported_back(self) -> None:
        # A selection the caller cannot see is a silent one.
        self.assertIn("record LogSelectionPlan(", self.src)


class DispatchWiring(unittest.TestCase):
    """The request reaches the adapter, and it is validated before dispatch."""

    def test_bridge_server_validates_and_forwards_root(self) -> None:
        src = _read(BRIDGE_SERVER)
        self.assertIn('if (op == "enable-own-graph-logging") EditorAdapter.ValidateOwnGraphLogging(root);', src)
        self.assertIn('op == "enable-own-graph-logging" ? _adapter.EnableOwnGraphLogging(root)', src)

    def test_adapter_takes_and_reads_the_request(self) -> None:
        src = _read(EDITOR_ADAPTER)
        self.assertIn("public object EnableOwnGraphLogging(JsonElement request)", src)
        self.assertIn("OwnGraphLogSelectionRequest(request)", src)
        # the selection plan is surfaced in the reply, so the caller can see WHAT was picked.
        self.assertIn("selection=selectionPlan", src)


class DirectCallCarriesIds(unittest.TestCase):
    """call-bridge.ps1 can carry the id -- and it is directly invocable, no queue."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read(CALL_BRIDGE)

    def test_op_is_in_the_validate_set(self) -> None:
        self.assertIn(f"'{OP}'", self.src)

    def test_ids_are_forwarded_verbatim(self) -> None:
        self.assertIn("$request['ids']=$Ids", self.src)

    def test_ids_forwarding_is_not_restricted_by_op(self) -> None:
        # The single forwarding line carries no op guard in front of it; only the
        # payload-owning ops above it gate their OWN fields.
        lines = [ln.strip() for ln in self.src.splitlines() if "$request['ids']=$Ids" in ln]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("if($null -ne $Ids"))


# --- PowerShell AST probe (part D): the QUEUE still refuses ids for this op -------------
_PROBE_HEAD = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__RUNNER__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$fn = $ast.Find({ param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq 'Get-ValidatedCallArguments' }, $true)
if ($null -eq $fn) { throw 'MISSING_Get-ValidatedCallArguments' }
. ([scriptblock]::Create($fn.Extent.Text))
$run = '11111111-1111-1111-1111-111111111111'
$out = [ordered]@{}
function Case([string]$name, [scriptblock]$body) {
  try {
    $a = & $body
    $keys = @(); foreach ($k in $a.Keys) { $keys += [string]$k }
    $out[$name] = [ordered]@{ ok = $true; keys = @($keys | Sort-Object) }
  } catch {
    $out[$name] = [ordered]@{ ok = $false; error = [string]$_.Exception.Message }
  }
}
"""
_PROBE_TAIL = "\n$out | ConvertTo-Json -Depth 8 -Compress\n"

CASES = (
    ("enable-no-ids",
     "Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='enable-own-graph-logging'})",
     ("keys", ("Operation", "RunId"))),
    # HONEST LIMIT: the queue path cannot name the graph -- the pinned runner's closed
    # schema admits `ids` for the node-query ops only, and this op is not one of them.
    ("enable-with-ids-refused-via-queue",
     "Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='enable-own-graph-logging';ids=@(1073741831)})",
     ("refuse", "IDS_NOT_ALLOWED")),
    ("enable-with-foreign-entryid",
     "Get-ValidatedCallArguments ([pscustomobject]@{kind='call';runId=$run;op='enable-own-graph-logging';entityId=5})",
     ("refuse", "CALL_FIELD_NOT_ALLOWED:entityId")),
)


def _powershell_host() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_probe(cases) -> dict:
    host = _powershell_host()
    if host is None:
        raise unittest.SkipTest("no PowerShell host to lift out the runner validator")
    parts = [_PROBE_HEAD.replace("__RUNNER__", str(RUNNER))]
    for name, body, _expect in cases:
        parts.append("Case '%s' { %s }" % (name, body))
    parts.append(_PROBE_TAIL)
    script = "\n".join(parts)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        [host, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, f"probe host exited {proc.returncode}:\n{proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe produced no stdout (stderr: {proc.stderr})"
    data = json.loads(lines[-1])
    for entry in data.values():
        if entry.get("ok") and isinstance(entry.get("keys"), str):
            entry["keys"] = [entry["keys"]]
    return data


class QueueSchemaStillClosed(unittest.TestCase):
    """Executed against the real runner -- pins the transport limit AND the shim's safety."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.verdicts = _run_probe(CASES)

    def test_all_cases_ran(self) -> None:
        self.assertEqual(set(self.verdicts), {name for name, _b, _e in CASES})

    def test_op_is_admitted_with_no_extra_fields(self) -> None:
        entry = self.verdicts["enable-no-ids"]
        self.assertTrue(entry["ok"], entry)
        self.assertEqual(tuple(entry["keys"]), ("Operation", "RunId"))

    def test_queue_cannot_carry_the_graph_id(self) -> None:
        entry = self.verdicts["enable-with-ids-refused-via-queue"]
        self.assertFalse(entry["ok"], entry)
        self.assertEqual(entry["error"], "IDS_NOT_ALLOWED")

    def test_foreign_fields_are_refused_by_name(self) -> None:
        entry = self.verdicts["enable-with-foreign-entryid"]
        self.assertFalse(entry["ok"], entry)
        self.assertEqual(entry["error"], "CALL_FIELD_NOT_ALLOWED:entityId")


if __name__ == "__main__":
    unittest.main(verbosity=2)
