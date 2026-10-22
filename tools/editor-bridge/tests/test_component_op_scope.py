#!/usr/bin/env python3
"""``entityId`` must be REFUSED BY NAME on a non-call kind, not silently ignored.

WHY THIS FILE EXISTS

``tools/editor-bridge/elevated-runner.ps1`` validates the shape of an untrusted queue
body in two places:

  * ``Assert-RequestIdsScope`` (~:169) -- runs for EVERY request kind, before dispatch
    (called at ~:901). It decides, per field, whether that field may appear at all.
  * ``Get-ValidatedCallArguments`` (~:240) -- runs only for a ``call`` (dispatched at
    ~:944) and applies the closed per-op allowlist.

That split matters. ``relativePath`` and the ``tag*`` fields are policed in
``Assert-RequestIdsScope`` so that a field meant for one operation is refused by name on
ANY other kind or op (:183-194), rather than being carried, unseen, onto a branch that
does not consume it. ``entityId`` -- added for the compiled ``inspect-entity-components``
probe -- was widened into the CALL allowlist only, so on a non-call body the field was
simply IGNORED: nothing in the kind branches reads ``entityId``, and with no scope gate it
never raised. A field the caller sent vanished without a refusal.

The mutation sibling ``delete-entity-component`` brings three more op-owned fields --
``probeId``, ``componentId`` (its own two, gated exactly like ``entityId``) and ``action``
(shared with ``native-scene``, so CALL-scoped rather than kind-scoped). Its ADD sibling
``add-entity-component`` owns the SAME three, and the ``delete-instruction-graph`` family
owns ``entityId`` (its edit-object id) but NOT ``action``. This file now pins all of them,
not just ``entityId``.

This file pins the fix: each op-owned field is gated exactly like ``relativePath``. A field
is refused unless the request is a ``call`` for the literally-spelled op that owns it.

WHAT IT ASSERTS

  a) the runner still PARSES clean (the edit must not break the pinned helper);
  b) behaviour: on a non-call kind (``fs``/``status``/``load``/``native-scene``) a body
     carrying ``entityId`` is REFUSED by name -- both the IDictionary (hashtable) and the
     PSObject (pscustomobject) paths, and for a case-variant field name;
  c) it is refused for a ``call`` to the WRONG op too (``ping``/``node-definitions``), and
     for case variants of the kind and op -- mirroring relativePath exactly;
  d) presence, not value: a null or zero ``entityId`` on a foreign kind is still refused;
  e) the legitimate path is untouched: a ``call`` for ``inspect-entity-components`` (or its
     ``delete-entity-component`` sibling) carrying the op-owned field is accepted, and a
     body with no such field is unaffected;
  f) the static gate exists and names the one allowed op;
  g) the DELETE op's own fields: ``probeId``/``componentId`` refused by name on a foreign op
     and accepted on ``delete-entity-component``; ``action`` refused on a foreign ``call``
     but left alone on ``native-scene`` (its other legitimate owner);
  h) NEGATIVE CONTROL: a temp copy with the delete-fields gate disabled lets a foreign call
     carrying ``probeId`` through, and the same verification that passes on the real runner
     raises on the mutant.

This file sends NO request. It introspects the runner with the PowerShell AST, dot-sources
the extracted pure function, and exercises it in-process. Nothing dispatches, connects,
creates a scope, or touches a queue, the helper, the editor or the game.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_component_op_scope
"""
from __future__ import annotations

import base64
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNNER = ROOT / "tools/editor-bridge/elevated-runner.ps1"

OP = "inspect-entity-components"
REFUSAL = "ENTITY_COMPONENT_ID_NOT_ALLOWED"
#: The delete op's own two fields (probeId/componentId) and its shared `action` field.
DELETE_FIELDS_REFUSAL = "COMPONENT_DELETE_FIELDS_NOT_ALLOWED"
ACTION_REFUSAL = "COMPONENT_ACTION_NOT_ALLOWED"
#: Precedent this gate mirrors; the parity control asserts it still fires on a foreign kind.
RELATIVE_PATH_REFUSAL = "SCRIPT_FILE_PROBE_PATH_NOT_ALLOWED"

#: name -> None if the scope function must ACCEPT the request, else the required
#: exception-message prefix. Every op-owned field except on its exact op must be refused.
EXPECTED = {
    # (b) non-call kinds carrying entityId are refused by name.
    "fs-entityId": REFUSAL,
    "status-entityId": REFUSAL,
    "load-entityId": REFUSAL,
    "native-entityId": REFUSAL,
    # (c) a call to the wrong op is refused, and case variants of kind/op/field too.
    "call-ping-entityId": REFUSAL,
    "call-nodedef-entityId": REFUSAL,
    "CALL-entityId": REFUSAL,
    "op-case-entityId": REFUSAL,
    "field-case-entityId": REFUSAL,
    # (d) presence, not value.
    "fs-entityId-null": REFUSAL,
    "fs-entityId-zero": REFUSAL,
    # (b) the IDictionary path, not just the PSObject path.
    "hashtable-fs-entityId": REFUSAL,
    # (e) the legitimate path is untouched.
    "inspect-ok": None,
    "inspect-ok-null": None,
    "fs-no-entityId": None,
    # parity control: the precedent still refuses on a foreign kind.
    "fs-relativePath": RELATIVE_PATH_REFUSAL,

    # (g) the DELETE op's own fields, gated exactly like entityId.
    "fs-probeId": DELETE_FIELDS_REFUSAL,
    "call-ping-probeId": DELETE_FIELDS_REFUSAL,
    "call-inspect-probeId": DELETE_FIELDS_REFUSAL,
    "field-case-probeId": DELETE_FIELDS_REFUSAL,
    "fs-componentId-zero": DELETE_FIELDS_REFUSAL,
    "hashtable-fs-componentId": DELETE_FIELDS_REFUSAL,
    "call-delete-accepted": None,
    "call-delete-probeId-accepted": None,
    # `action` is CALL-scoped: refused on a foreign call, untouched on native-scene.
    "call-ping-action": ACTION_REFUSAL,
    "call-delete-action-accepted": None,
    "native-action": None,

    # (i) the ADD sibling owns the same three fields as the delete op.
    "call-add-accepted": None,
    "call-add-probeId-accepted": None,
    "call-add-action-accepted": None,
    # (j) the instruction-graph family owns `entityId` (its edit-object id), and `action` is
    # NOT its field -- the read-only form is the separate -dry-run op NAME.
    "call-ig-entityid-accepted": None,
    "call-ig-action": ACTION_REFUSAL,
}

_HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$runner='__RUNNER__'
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){ Write-Output 'PARSE_ERRORS'; foreach($pe in $parseErrors){ Write-Output $pe.ToString() }; exit 2 }
$fn=$ast.Find({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq 'Assert-RequestIdsScope'},$true)
if($null -eq $fn){ Write-Output 'MISSING_FUNCTION'; exit 3 }
. ([scriptblock]::Create($fn.Extent.Text))
$script:out=New-Object System.Collections.Generic.List[string]
function Case([string]$name,[scriptblock]$action){
  $caught=$null
  try{ & $action | Out-Null }catch{ $caught=[string]$_.Exception.Message }
  if($null -eq $caught){ $script:out.Add($name + "`tOK") } else { $script:out.Add($name + "`t" + $caught) }
}
$run='11111111-1111-1111-1111-111111111111'
Case 'fs-entityId'           { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';entityId=7}) }
Case 'status-entityId'       { Assert-RequestIdsScope ([pscustomobject]@{kind='status';entityId=7}) }
Case 'load-entityId'         { Assert-RequestIdsScope ([pscustomobject]@{kind='load';targetPid=1;entityId=7}) }
Case 'native-entityId'       { Assert-RequestIdsScope ([pscustomobject]@{kind='native-scene';action='inspect';entityId=7}) }
Case 'call-ping-entityId'    { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='ping';entityId=7}) }
Case 'call-nodedef-entityId' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='node-definitions';ids=@(1);entityId=7}) }
Case 'CALL-entityId'         { Assert-RequestIdsScope ([pscustomobject]@{kind='CALL';runId=$run;op='inspect-entity-components';entityId=7}) }
Case 'op-case-entityId'      { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='INSPECT-ENTITY-COMPONENTS';entityId=7}) }
Case 'field-case-entityId'   { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';ENTITYID=7}) }
Case 'fs-entityId-null'      { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';entityId=$null}) }
Case 'fs-entityId-zero'      { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';entityId=0}) }
Case 'hashtable-fs-entityId' { Assert-RequestIdsScope (@{kind='fs';op='write';entityId=7}) }
Case 'inspect-ok'            { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='inspect-entity-components';entityId=7}) }
Case 'inspect-ok-null'       { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='inspect-entity-components';entityId=$null}) }
Case 'fs-no-entityId'        { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';path='x'}) }
Case 'fs-relativePath'       { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';relativePath='a.lua'}) }
Case 'fs-probeId'            { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';probeId='deadbeef'}) }
Case 'call-ping-probeId'     { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='ping';probeId='deadbeef'}) }
Case 'call-inspect-probeId'  { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='inspect-entity-components';probeId='deadbeef'}) }
Case 'field-case-probeId'    { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';PROBEID='deadbeef'}) }
Case 'fs-componentId-zero'   { Assert-RequestIdsScope ([pscustomobject]@{kind='fs';op='write';componentId=0}) }
Case 'hashtable-fs-componentId' { Assert-RequestIdsScope (@{kind='fs';op='write';componentId=9}) }
Case 'call-delete-accepted'  { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='delete-entity-component';entityId=7}) }
Case 'call-delete-probeId-accepted' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='delete-entity-component';probeId='deadbeef';componentId=9}) }
Case 'call-ping-action'      { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='ping';action='inspect'}) }
Case 'call-delete-action-accepted' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='delete-entity-component';action='delete'}) }
Case 'native-action'         { Assert-RequestIdsScope ([pscustomobject]@{kind='native-scene';action='inspect'}) }
Case 'call-add-accepted'     { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='add-entity-component';entityId=7}) }
Case 'call-add-probeId-accepted' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='add-entity-component';probeId='deadbeef';componentId=9}) }
Case 'call-add-action-accepted' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='add-entity-component';action='add'}) }
Case 'call-ig-entityid-accepted' { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='delete-instruction-graph';entityId=7}) }
Case 'call-ig-action'        { Assert-RequestIdsScope ([pscustomobject]@{kind='call';runId=$run;op='delete-instruction-graph';action='delete'}) }
$script:out -join "`n"
"""

#: The delete-fields scope gate's op test, as it must appear in the runner. The negative
#: control disables a copy of it. The substring is the FULL op test (op name included), not
#: just the thrown code, so it stays unique now that the add sibling throws the same code.
_DELETE_FIELDS_GATE = (
    "$props['op'] -cnotin @('delete-entity-component','add-entity-component')){throw 'COMPONENT_DELETE_FIELDS_NOT_ALLOWED'}")


def _powershell() -> str | None:
    for exe in ("powershell", "pwsh"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def _run_harness(runner: pathlib.Path = RUNNER) -> dict[str, str]:
    exe = _powershell()
    if exe is None:
        raise unittest.SkipTest("no PowerShell on PATH; scope behaviour cannot be exercised")
    script = _HARNESS.replace("__RUNNER__", str(runner).replace("/", "\\"))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # -Command / -EncodedCommand are not governed by the script execution policy, so no
    # policy flag is passed; the runner is only ever parsed, never executed as a script.
    proc = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    out = (proc.stdout or "").strip()
    if "PARSE_ERRORS" in out:
        raise AssertionError(f"the runner no longer parses clean:\n{out}\n{proc.stderr}")
    if "MISSING_FUNCTION" in out:
        raise AssertionError("Assert-RequestIdsScope is gone -- the AST extractor found no such function")
    if proc.returncode not in (0, None):
        raise AssertionError(f"harness exited {proc.returncode}:\n{out}\n{proc.stderr}")
    results: dict[str, str] = {}
    for line in out.splitlines():
        if "\t" in line:
            name, value = line.split("\t", 1)
            results[name.strip()] = value.strip()
    if set(results) != set(EXPECTED):
        raise AssertionError(
            "the harness did not report exactly the expected cases.\n"
            f"missing={sorted(set(EXPECTED) - set(results))} extra={sorted(set(results) - set(EXPECTED))}\n{out}"
        )
    return results


class EntityIdScopeBehaviour(unittest.TestCase):
    """(b)-(e)+(g) run the extracted scope function against every case in-process."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.results = _run_harness()

    def _verify(self, results: dict[str, str]) -> None:
        """Raise AssertionError listing every case whose verdict is wrong.

        Deliberately NOT subTest-based: the negative control wraps this in
        ``assertRaises(AssertionError)`` to prove the check is load-bearing.
        """
        problems: list[str] = []
        for name, expected in EXPECTED.items():
            got = results.get(name)
            if got is None:
                problems.append(f"{name}: the harness reported no verdict")
            elif expected is None:
                if got != "OK":
                    problems.append(f"{name}: the request must be ACCEPTED, got `{got}`")
            elif not got.startswith(expected):
                problems.append(f"{name}: expected a refusal beginning `{expected}`, got `{got}`")
        if problems:
            self.fail("scope verdict mismatch:\n  " + "\n  ".join(problems))

    def test_every_case_matches_its_expected_verdict(self) -> None:
        self._verify(self.results)

    def test_non_call_kind_refusal_names_entity_id_not_something_else(self) -> None:
        """The refusal must be the entityId gate's own name, not a generic field refusal."""
        for name in ("fs-entityId", "status-entityId", "load-entityId", "native-entityId"):
            with self.subTest(case=name):
                self.assertTrue(
                    self.results[name].startswith(REFUSAL),
                    f"{name}: a non-call kind carrying entityId must be refused as {REFUSAL}",
                )

    def test_case_variants_do_not_slip_past(self) -> None:
        for name in ("CALL-entityId", "op-case-entityId", "field-case-entityId"):
            with self.subTest(case=name):
                self.assertTrue(
                    self.results[name].startswith(REFUSAL),
                    f"{name}: a casing variant must not bypass the entityId scope gate",
                )

    def test_delete_op_owned_fields_are_gated_by_name(self) -> None:
        """(g) probeId/componentId refused on a foreign op; accepted on delete; `action`
        refused on a foreign call but untouched on native-scene."""
        required = {
            "fs-probeId": DELETE_FIELDS_REFUSAL,
            "call-ping-probeId": DELETE_FIELDS_REFUSAL,
            "call-inspect-probeId": DELETE_FIELDS_REFUSAL,
            "field-case-probeId": DELETE_FIELDS_REFUSAL,
            "fs-componentId-zero": DELETE_FIELDS_REFUSAL,
            "hashtable-fs-componentId": DELETE_FIELDS_REFUSAL,
            "call-ping-action": ACTION_REFUSAL,
            "call-delete-accepted": None,
            "call-delete-probeId-accepted": None,
            "call-delete-action-accepted": None,
            "native-action": None,
            # (i)+(j) the add sibling and the instruction-graph family, same gate, same shape.
            "call-add-accepted": None,
            "call-add-probeId-accepted": None,
            "call-add-action-accepted": None,
            "call-ig-entityid-accepted": None,
            "call-ig-action": ACTION_REFUSAL,
        }
        for name, expected in required.items():
            with self.subTest(case=name):
                got = self.results[name]
                if expected is None:
                    self.assertEqual(got, "OK",
                                     f"{name}: the legitimate request must be ACCEPTED, got `{got}`")
                else:
                    self.assertTrue(
                        got.startswith(expected),
                        f"{name}: expected `{expected}`, got `{got}`")

    def test_negative_control_breaking_the_delete_fields_gate_breaks_this_test(self) -> None:
        """(h) Disabling the delete-fields scope gate in a temp copy must fail ``_verify``.

        The mutation neutralises the op test so a foreign ``call`` carrying ``probeId`` is
        no longer refused. The real runner refuses it; the mutant accepts it -- a verdict
        ``_verify``, which passes on the real runner, must reject.
        """
        self.assertTrue(self.results["call-ping-probeId"].startswith(DELETE_FIELDS_REFUSAL),
                        "precondition: the real runner must refuse probeId on a foreign call")

        text = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(text.count(_DELETE_FIELDS_GATE), 1,
                         "the delete-fields gate moved -- update the negative control")
        mutated_text = text.replace(_DELETE_FIELDS_GATE, "$false){throw 'COMPONENT_DELETE_FIELDS_NOT_ALLOWED'}")

        scratch = ROOT / ".runtime" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(dir=scratch))
        try:
            mutant = tmp / "elevated-runner.mutated.ps1"
            mutant.write_text(mutated_text, encoding="utf-8")
            mutated = _run_harness(mutant)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # The neutralised gate lets the foreign probeId through.
        self.assertEqual(mutated["call-ping-probeId"], "OK",
                         "disabling the gate must let a foreign call's probeId slip past")
        # ... and that is precisely the verdict ``_verify`` rejects.
        with self.assertRaises(AssertionError):
            self._verify(mutated)


class RunnerSourceGate(unittest.TestCase):
    """(a)+(f) the runner parses clean and the static gate names the one allowed op."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_runner_parses_clean(self) -> None:
        exe = _powershell()
        if exe is None:
            self.skipTest("no PowerShell on PATH")
        cmd = (
            f"$t=$null;$e=$null;"
            f"[Management.Automation.Language.Parser]::ParseFile('{str(RUNNER).replace('/', chr(92))}',[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1}else{'PARSE_CLEAN'}"
        )
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(proc.stdout.strip(), "PARSE_CLEAN",
                         f"elevated-runner.ps1 must stay parse-clean:\n{proc.stdout}\n{proc.stderr}")

    def test_scope_gate_refuses_entity_id_under_the_inspect_op_guard(self) -> None:
        """The scope gate must exist, throw the named refusal, and name the allowlist op."""
        block = re.search(
            r"-ieq\s*'entityId'.*?throw\s*'" + REFUSAL + r"'",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(
            block,
            f"Assert-RequestIdsScope has no `-ieq 'entityId' ... throw '{REFUSAL}'` gate",
        )
        assert block is not None
        self.assertIn(
            OP, block.group(0),
            "the entityId scope gate must be keyed on the inspect-entity-components op",
        )
        # It must test the kind, so a non-call body can never pass.
        self.assertIn("-cne 'call'", block.group(0),
                      "the entityId scope gate must require kind == 'call'")

    def test_scope_gate_names_the_delete_op_for_its_owned_fields(self) -> None:
        """The delete-fields gate must exist, throw its named refusal, and name the op."""
        block = re.search(
            r"\$componentDeleteFields.*?throw\s*'" + DELETE_FIELDS_REFUSAL + r"'",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(
            block,
            f"Assert-RequestIdsScope has no `$componentDeleteFields ... throw '{DELETE_FIELDS_REFUSAL}'` gate",
        )
        assert block is not None
        self.assertIn("delete-entity-component", block.group(0),
                      "the delete-fields scope gate must be keyed on delete-entity-component")


if __name__ == "__main__":
    unittest.main(verbosity=2)
