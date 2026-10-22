#!/usr/bin/env python3
"""Pin the OWNERSHIP gate and the request envelope in front of ``delete-instruction-graph``.

WHY THIS FILE EXISTS

``InstructionGraphDelete.DeleteInstructionGraph`` is a MUTATION: it fires the native
``beyondEditObjService.DeleteInstructionGraphForEditObj`` command -- the symmetric
sibling of the ``AddInstructionGraphForEditObj`` the bridge already uses to BIND a graph.
An over-broad gate would let a request destroy a graph a USER created, and the level
carries user graphs alongside this project's.

Three properties are load-bearing, and this file pins all three:

  1. OWNERSHIP BY IDENTITY. The target must be a Kind-9 resource from the SAME
     ``Resources()`` walk the rest of the bridge uses, whose id resolves to exactly ONE
     row, whose stored name starts with ``MW_`` (this project's own graph prefix -- the
     SAME constant the sibling ``OwnedGraphDelete`` uses). A graph someone else made is
     refused BY NAME even if its id and name are supplied.

  2. FAIL-CLOSED ON STATE. A graph that has NODES is refused unless the caller explicitly
     asks for the wider form by naming the ``-force`` op; a graph with entity BINDINGS is
     refused unconditionally -- no op name lifts that. The edit-object id is REQUIRED
     (tier-3: the native payload shape is unrecovered), so an id-less request is refused
     with a named code rather than defaulted.

  3. THE RUNNER GAP WAS NAMED, AND IS NOW CLOSED. ``elevated-runner.ps1`` used to admit no
     payload field for this op: ``entityId`` -> ``ENTITY_COMPONENT_ID_NOT_ALLOWED`` (the
     ``Assert-RequestIdsScope`` gate, :204-207) and ``ids`` -> ``IDS_NOT_ALLOWED`` (the
     ``$nodeQueryOps`` scope), so the op was unreachable from the queue and only a BARE
     body reached ``call-bridge.ps1``. The runner now narrows a per-op list for the whole
     family (a REPLACED list -- ``{ids, entityId}``, never widened, exactly like the two
     component ops), so ``ids``+``entityId`` reach ``call-bridge.ps1`` and the op can be
     invoked. ``test_the_family_reaches_call_bridge_with_its_own_fields`` states that
     verdict; ``test_negative_control_removing_the_edit_object_field_flips_a_verdict``
     proves the accept path is load-bearing.

HOW IT IS TESTED (no request is ever sent)

The gate needs a LIVE editor, so it cannot be executed here. This file does what the
repo's other gate tests do:

  * SOURCE FIDELITY -- every named refusal the model below can raise must appear in the
    C# source, so the transcribed model and the shipped code cannot drift apart.
  * DECISION MODEL -- the envelope and the ownership gate are transcribed into runnable
    Python and driven with synthetic registry/entity objects (missing/2 ids, zero id,
    missing edit-object id, unknown field, foreign name, no graphs, not found, ambiguous,
    non-empty, bound, and the two accept paths).
  * RUNNER BEHAVIOUR -- the pinned runner's two validators are lifted out with the
    PowerShell AST and EXECUTED against a table of untrusted queue bodies (the same
    technique as ``test_component_op_plumbing``), plus a NEGATIVE CONTROL that drops
    ``entityId`` from the family's per-op allowlist in a temp copy and flips a verdict.

Usage:  python -B tools/editor-bridge/tests/test_instruction_graph_delete_safety.py
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = ROOT / "tools/editor-bridge/Adapter/InstructionGraphDelete.cs"
RUNNER = ROOT / "tools/editor-bridge/elevated-runner.ps1"
BRIDGE_SERVER = ROOT / "tools/editor-bridge/ManagedBridge/BridgeServer.cs"
CALL_BRIDGE = ROOT / "tools/editor-bridge/call-bridge.ps1"
CSPROJ = ROOT / "tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj"

OPS = ("delete-instruction-graph", "delete-instruction-graph-force",
       "delete-instruction-graph-dry-run")


class Refusal(Exception):
    pass


# --------------------------------------------------------------------------- #
# Decision model A -- the request envelope (ValidateInstructionGraphDelete)
# --------------------------------------------------------------------------- #
ALLOWED = {"id", "op", "nonce", "ids", "entityId"}


def validate(request: dict) -> dict:
    for name in request:
        if name not in ALLOWED:
            raise Refusal("INSTRUCTION_GRAPH_UNKNOWN_OR_DUPLICATE_FIELD:" + name)
    if len(request) != len(set(request)):
        raise Refusal("INSTRUCTION_GRAPH_DUPLICATE_KEY")
    ids = request.get("ids")
    if not isinstance(ids, list):
        raise Refusal("INSTRUCTION_GRAPH_IDS_REQUIRED")
    if len(ids) == 0:
        raise Refusal("INSTRUCTION_GRAPH_IDS_REQUIRED")
    if len(ids) != 1:
        raise Refusal("INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED")
    if not isinstance(ids[0], int) or ids[0] <= 0 or ids[0] > 4294967295:
        raise Refusal("INSTRUCTION_GRAPH_ID_INVALID")
    eid = request.get("entityId")
    if not isinstance(eid, int) or eid <= 0 or eid > 4294967295:
        raise Refusal("INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")
    return {"graphId": ids[0], "editObjId": eid}


# --------------------------------------------------------------------------- #
# Decision model B -- the ownership gate (InstructionGraphOwnedTarget + state checks)
# --------------------------------------------------------------------------- #
MW_PREFIX = "MW_"


def owned_target(graph_id: int, resources: list[dict]) -> dict:
    rows = [r for r in resources if r["kind"] == 9 and r["id"] == graph_id]
    if not rows:
        if not any(r["kind"] == 9 for r in resources):
            raise Refusal("INSTRUCTION_GRAPH_NO_GRAPHS_VISIBLE")
        raise Refusal("INSTRUCTION_GRAPH_NOT_FOUND")
    if len(rows) > 1:
        raise Refusal("INSTRUCTION_GRAPH_ID_AMBIGUOUS")
    graph = rows[0]
    if graph["name"] is None:
        raise Refusal("INSTRUCTION_GRAPH_NAME_UNAVAILABLE")
    if not graph["name"].startswith(MW_PREFIX):
        raise Refusal("INSTRUCTION_GRAPH_FOREIGN_NOT_OWNED:" + graph["name"])
    return graph


def delete_precheck(graph: dict, force: bool) -> None:
    if graph["boundEntityIds"]:
        raise Refusal("INSTRUCTION_GRAPH_BOUND")
    if not force and graph["nodeCount"] != 0:
        raise Refusal("INSTRUCTION_GRAPH_NOT_EMPTY:" + str(graph["nodeCount"]))


def graph(id_: int, name: str | None, node_count: int = 0, bound=()) -> dict:
    return {"kind": 9, "id": id_, "name": name, "nodeCount": node_count,
            "boundEntityIds": list(bound)}


#: Every refusal the two models can raise. Each must appear in the C# source.
NAMED_REFUSALS = (
    "INSTRUCTION_GRAPH_UNKNOWN_OR_DUPLICATE_FIELD",
    "INSTRUCTION_GRAPH_IDS_REQUIRED",
    "INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED",
    "INSTRUCTION_GRAPH_ID_INVALID",
    "INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED",
    "INSTRUCTION_GRAPH_NO_GRAPHS_VISIBLE",
    "INSTRUCTION_GRAPH_NOT_FOUND",
    "INSTRUCTION_GRAPH_ID_AMBIGUOUS",
    "INSTRUCTION_GRAPH_NAME_UNAVAILABLE",
    "INSTRUCTION_GRAPH_FOREIGN_NOT_OWNED",
    "INSTRUCTION_GRAPH_NOT_EMPTY",
    "INSTRUCTION_GRAPH_BOUND",
    "INSTRUCTION_GRAPH_ALREADY_ATTEMPTED",
    "INSTRUCTION_GRAPH_LEASE_MUTATION_LIMIT",
    "INSTRUCTION_GRAPH_TARGET_CHANGED_DURING_PREPARATION",
    "EDITOR_NOT_READY",
)


class TestSourceFidelity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_source_is_present_and_non_trivial(self) -> None:
        self.assertIn("sealed partial class EditorAdapter", self.text)
        self.assertGreater(len(self.text), 6000)

    def test_every_named_refusal_reaches_the_source(self) -> None:
        for code in NAMED_REFUSALS:
            self.assertIn(f'"{code}', self.text, f"{code} is not raised by the shipped code")

    def test_ownership_gate_reuses_the_sibling_mw_prefix(self) -> None:
        # The SAME constant the sibling graph deleter gates on -- never a second literal.
        self.assertIn("OwnedGraphDeleteNamePrefix", self.text)
        code = self.text[self.text.index("internal sealed partial class"):]
        self.assertNotIn('"MW_"', code)
        self.assertIn("StartsWith(OwnedGraphDeleteNamePrefix", code)

    def test_dispatch_mirrors_the_attested_add_sibling(self) -> None:
        self.assertIn('const string InstructionGraphDeleteService = "beyondEditObjService";', self.text)
        self.assertIn('const string InstructionGraphDeleteCommand = "DeleteInstructionGraphForEditObj";', self.text)
        # Same producer call and the same four wrapper slots the Add path uses.
        self.assertIn('B("Ikci0qkvMZX")', self.text)
        self.assertIn('B("h8diA3iOGmJ")', self.text)   # bool
        self.assertIn('B("bKliA0tj1p1")', self.text)   # uint (editObjId AND graphId)
        self.assertIn('B("qsriAuLLSBe")', self.text)   # uint 1u
        # The three tiers must be stated, not implied.
        self.assertIn("preimage-not-literal(0x2c4eda76)", self.text)
        self.assertIn("commandPayloadTier", self.text)

    def test_status_strings_are_the_ones_callers_read(self) -> None:
        self.assertIn("instruction-graph-delete-requested-readback-pending", self.text)
        self.assertIn("instruction-graph-delete-dry-run-mapping-only", self.text)
        for flag in ("nativeMutationInvoked", "localModelWritten", "gameEffectVerified",
                     "persistentSaveVerified", "retryAllowed"):
            self.assertIn(flag, self.text)

    def test_dry_run_invokes_nothing(self) -> None:
        body = self.text[self.text.index("public object DeleteInstructionGraphDryRun"):]
        self.assertNotIn("DispatchInstructionGraphDelete", body)
        self.assertIn("invoked = false", body)
        self.assertIn("nativeMutationInvoked = false", body)
        self.assertIn("wouldRefuse", body)


class TestRequestEnvelope(unittest.TestCase):
    def _refuses(self, code: str, request: dict) -> None:
        with self.assertRaises(Refusal) as ctx:
            validate(request)
        self.assertEqual(str(ctx.exception), code)

    def test_accepts_one_id_plus_edit_object(self) -> None:
        self.assertEqual(validate({"op": OPS[0], "ids": [1073741830], "entityId": 7}),
                         {"graphId": 1073741830, "editObjId": 7})

    def test_refuses_a_missing_id_list(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_IDS_REQUIRED", {"op": OPS[0], "entityId": 7})

    def test_refuses_an_empty_id_list(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_IDS_REQUIRED", {"op": OPS[0], "ids": [], "entityId": 7})

    def test_refuses_two_ids(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED",
                      {"op": OPS[0], "ids": [1, 2], "entityId": 7})

    def test_refuses_a_zero_id(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_ID_INVALID", {"op": OPS[0], "ids": [0], "entityId": 7})

    def test_refuses_a_missing_edit_object_id(self) -> None:
        # Tier (3): the payload shape is unrecovered, so the edit-object id is REQUIRED.
        self._refuses("INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED", {"op": OPS[0], "ids": [9]})

    def test_refuses_an_unknown_or_duplicate_field(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_UNKNOWN_OR_DUPLICATE_FIELD:action",
                      {"op": OPS[0], "ids": [9], "entityId": 7, "action": "delete"})


class TestOwnershipGate(unittest.TestCase):
    STRANGER = graph(4242, "User_MyLevel_Graph")

    def _refuses(self, code: str, fn, *args) -> None:
        with self.assertRaises(Refusal) as ctx:
            fn(*args)
        self.assertEqual(str(ctx.exception), code)

    def test_refuses_a_foreign_graph_by_name(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_FOREIGN_NOT_OWNED:User_MyLevel_Graph",
                      owned_target, 4242, [self.STRANGER])

    def test_refuses_when_no_graph_is_visible(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_NO_GRAPHS_VISIBLE", owned_target, 4242, [])

    def test_refuses_an_id_that_is_not_a_graph(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_NOT_FOUND", owned_target, 4242, [graph(99, "MW_Other")])

    def test_refuses_an_ambiguous_id(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_ID_AMBIGUOUS", owned_target, 4242,
                      [graph(4242, "MW_A"), graph(4242, "MW_A")])

    def test_refuses_an_unreadable_name(self) -> None:
        self._refuses("INSTRUCTION_GRAPH_NAME_UNAVAILABLE", owned_target, 4242, [graph(4242, None)])

    def test_refuses_a_non_empty_graph_unless_forced(self) -> None:
        stray = graph(1073741830, "MW_API_DEMO_RUN", node_count=17)
        self._refuses("INSTRUCTION_GRAPH_NOT_EMPTY:17", delete_precheck, stray, False)
        delete_precheck(stray, True)  # -force is the explicit override

    def test_force_never_lifts_the_binding_refusal(self) -> None:
        bound = graph(1073741830, "MW_API_DEMO_RUN", node_count=0, bound=[1094713345])
        self._refuses("INSTRUCTION_GRAPH_BOUND", delete_precheck, bound, True)

    def test_accepts_the_empty_unbound_stray(self) -> None:
        stray = graph(1073741830, "MW_API_DEMO_RUN")
        self.assertEqual(owned_target(1073741830, [stray]), stray)
        delete_precheck(stray, False)


# --------------------------------------------------------------------------- #
# Runner behaviour -- lift the pinned validators with the PowerShell AST
# --------------------------------------------------------------------------- #
_PROBE_HEAD = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__RUNNER__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($want in @('Assert-RequestIdsScope','Get-ValidatedCallArguments')) {
  $fn = $ast.Find({ param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq $want }, $true)
  if ($null -eq $fn) { throw ('MISSING_' + $want) }
  . ([scriptblock]::Create($fn.Extent.Text))
}
$run = '11111111-1111-1111-1111-111111111111'
$out = [ordered]@{}
function Case([string]$name, [scriptblock]$body) {
  try {
    $o = & $body
    Assert-RequestIdsScope $o
    $a = Get-ValidatedCallArguments $o
    $keys = @(); foreach ($k in $a.Keys) { $keys += [string]$k }
    $out[$name] = [ordered]@{ ok = $true; keys = @($keys | Sort-Object) }
  } catch {
    $out[$name] = [ordered]@{ ok = $false; error = [string]$_.Exception.Message }
  }
}
"""
_PROBE_TAIL = "\n$out | ConvertTo-Json -Depth 8 -Compress\n"
#: The family's per-op allowlist as it must appear in the runner (a REPLACED list, never
#: widened). The negative control drops `entityId` from a copy of it.
_IG_ALLOWLIST = ("$allowedFields=@('kind','runId','op','ids','entityId')")


def _powershell_host() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_probe(runner: pathlib.Path, cases) -> dict:
    host = _powershell_host()
    if host is None:
        raise unittest.SkipTest("no PowerShell host to lift out the runner validators")
    parts = [_PROBE_HEAD.replace("__RUNNER__", str(runner))]
    for name, body, _expect in cases:
        parts.append("Case '%s' { %s }" % (name, body))
    parts.append(_PROBE_TAIL)
    encoded = base64.b64encode("\n".join(parts).encode("utf-16-le")).decode("ascii")
    proc = subprocess.run([host, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=180)
    assert proc.returncode == 0, f"probe host exited {proc.returncode}:\n{proc.stderr}"
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, f"probe produced no stdout (stderr: {proc.stderr})"
    data = json.loads(lines[-1])
    for entry in data.values():
        if entry.get("ok") and isinstance(entry.get("keys"), str):
            entry["keys"] = [entry["keys"]]
    return data


def _obj(body: str) -> str:
    return "[pscustomobject]@{" + body + "}"


#: name -> (untrusted queue body, expectation: ('keys', (...)) or ('refuse', code))
CASES = (
    # A positive control found by the SAME method: a node query the runner DOES admit.
    ("control-node-accept-ids",
     _obj("kind='call';runId=$run;op='node-definitions';ids=@(1,2,3)"),
     ("keys", ("Ids", "Operation", "RunId"))),

    # The family carries its two op-owned fields end-to-end: `ids` (one graph id) and
    # `entityId` (the edit-object id). This is the reachability property the fix restores.
    ("ig-accept-ids-and-editobj",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';ids=@(1073741830);entityId=7"),
     ("keys", ("EntityId", "Ids", "Operation", "RunId"))),
    ("ig-accept-force",
     _obj("kind='call';runId=$run;op='delete-instruction-graph-force';ids=@(1073741830);entityId=7"),
     ("keys", ("EntityId", "Ids", "Operation", "RunId"))),
    ("ig-accept-dry-run",
     _obj("kind='call';runId=$run;op='delete-instruction-graph-dry-run';ids=@(1073741830);entityId=7"),
     ("keys", ("EntityId", "Ids", "Operation", "RunId"))),

    # ... and each op-owned field is REQUIRED, refused by the family's own named code.
    ("ig-refuse-bare",
     _obj("kind='call';runId=$run;op='delete-instruction-graph'"),
     ("refuse", "INSTRUCTION_GRAPH_IDS_REQUIRED")),
    ("ig-refuse-ids-only",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';ids=@(1073741830)"),
     ("refuse", "INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")),
    ("ig-refuse-entityid-only",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';entityId=7"),
     ("refuse", "INSTRUCTION_GRAPH_IDS_REQUIRED")),
    ("ig-refuse-two-ids",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';ids=@(1,2);entityId=7"),
     ("refuse", "INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED")),
    ("ig-refuse-zero-id",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';ids=@(0);entityId=7"),
     ("refuse", "INSTRUCTION_GRAPH_ID_INVALID")),
    ("ig-refuse-zero-editobj",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';ids=@(1);entityId=0"),
     ("refuse", "INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")),
    # probeId is still a foreign field for this family: it belongs to the component ops.
    ("ig-refuse-probeid",
     _obj("kind='call';runId=$run;op='delete-instruction-graph';probeId='0123456789abcdef0123456789abcdef'"),
     ("refuse", "COMPONENT_DELETE_FIELDS_NOT_ALLOWED")),
)


class TestRunnerGap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = _run_probe(RUNNER, CASES)

    def test_every_case_matches_its_expected_verdict(self) -> None:
        for name, _body, expect in CASES:
            entry = self.results[name]
            if expect[0] == "keys":
                self.assertTrue(entry.get("ok"), f"{name}: {entry}")
                self.assertEqual(tuple(entry["keys"]), expect[1], name)
            else:
                self.assertFalse(entry.get("ok"), f"{name} must refuse")
                self.assertEqual(entry["error"], expect[1], name)

    def test_the_family_reaches_call_bridge_with_its_own_fields(self) -> None:
        """The reachability verdict after the fix: ids+entityId reach call-bridge.ps1."""
        for name in ("ig-accept-ids-and-editobj", "ig-accept-force", "ig-accept-dry-run"):
            entry = self.results[name]
            self.assertTrue(entry.get("ok"), f"{name}: {entry}")
            self.assertEqual(tuple(entry["keys"]), ("EntityId", "Ids", "Operation", "RunId"), name)

    def test_closed_schema_refuses_a_half_body_on_the_validator_alone(self) -> None:
        """``Get-ValidatedCallArguments`` ALONE refuses a body carrying only one of the two
        op-owned fields.

        Loaded from ``test_component_op_plumbing`` rather than duplicated: that module
        already lifts ``Get-ValidatedCallArguments`` out of the runner and drives it with an
        untrusted body (no ``Assert-RequestIdsScope``). Both named codes are anchored here so
        the family's own branch -- not a foreign-field refusal -- is what answers a half body.
        """
        import importlib.util
        import sys
        sibling = ROOT / "tools/editor-bridge/tests/test_component_op_plumbing.py"
        spec = importlib.util.spec_from_file_location("_sibling_plumbing", sibling)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_sibling_plumbing"] = module
        spec.loader.exec_module(module)
        cases = (
            ("ig-entityid-only-closed-schema",
             module._call("kind='call';runId=$run;op='delete-instruction-graph';entityId=7"),
             module._refuse("INSTRUCTION_GRAPH_IDS_REQUIRED")),
            ("ig-ids-only-closed-schema",
             module._call("kind='call';runId=$run;op='delete-instruction-graph';ids=@(1)"),
             module._refuse("INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")),
        )
        verdicts = module._run_call_probe(RUNNER, cases)
        self.assertFalse(verdicts["ig-entityid-only-closed-schema"].get("ok"))
        self.assertEqual(verdicts["ig-entityid-only-closed-schema"]["error"],
                         "INSTRUCTION_GRAPH_IDS_REQUIRED")
        self.assertFalse(verdicts["ig-ids-only-closed-schema"].get("ok"))
        self.assertEqual(verdicts["ig-ids-only-closed-schema"]["error"],
                         "INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")

    def test_negative_control_removing_the_edit_object_field_flips_a_verdict(self) -> None:
        """Dropping ``entityId`` from the family's per-op allowlist in a temp copy must flip a
        verdict: the real runner ACCEPTS the ids+edit-object body, the mutant refuses it with
        ``CALL_FIELD_NOT_ALLOWED:entityId`` -- a verdict ``TestRunnerGap`` rejects, so the
        accept case and the two half-body refusals are load-bearing, not incidental."""
        self.assertTrue(self.results["ig-accept-ids-and-editobj"].get("ok"),
                        "precondition: the real runner must accept ids+editobj")
        text = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(text.count(_IG_ALLOWLIST), 1,
                         "the instruction-graph allowlist site moved -- update the negative control")
        mutant = text.replace(_IG_ALLOWLIST, _IG_ALLOWLIST.replace(",'entityId'", ""))
        scratch = ROOT / ".runtime" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(dir=scratch))
        try:
            path = tmp / "elevated-runner.mutated.ps1"
            path.write_text(mutant, encoding="utf-8")
            flipped = _run_probe(path, CASES)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(flipped["ig-accept-ids-and-editobj"].get("error"),
                         "CALL_FIELD_NOT_ALLOWED:entityId",
                         "dropping entityId must refuse the body by name")
        with self.assertRaises(AssertionError):
            for name, _body, expect in CASES:
                entry = flipped[name]
                if expect[0] == "keys":
                    self.assertTrue(entry.get("ok"), f"{name}: {entry}")
                    self.assertEqual(tuple(entry["keys"]), expect[1], name)
                else:
                    self.assertFalse(entry.get("ok"), f"{name} must refuse")
                    self.assertEqual(entry["error"], expect[1], name)


class TestWiring(unittest.TestCase):
    def test_call_bridge_validateset_lists_all_three_ops(self) -> None:
        text = CALL_BRIDGE.read_text(encoding="utf-8")
        head = text[:text.index("$ErrorActionPreference")]
        for op in OPS:
            self.assertIn(f"'{op}'", head, f"{op} missing from the ValidateSet")

    def test_bridge_server_dispatches_all_three_ops(self) -> None:
        text = BRIDGE_SERVER.read_text(encoding="utf-8")
        for op in OPS:
            self.assertIn(f'case "{op}":', text, f"{op} has no dispatch case")
        self.assertIn("ValidateInstructionGraphDelete(root)", text)

    def test_csproj_compiles_the_adapter(self) -> None:
        self.assertIn("../Adapter/InstructionGraphDelete.cs", CSPROJ.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
