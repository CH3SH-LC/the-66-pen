#!/usr/bin/env python3
"""The component call ops' per-op allowlist is a BEHAVIOUR: assert it by running it.

WHY THIS FILE EXISTS

``tools/editor-bridge/Adapter/EntityComponentProbe.cs`` is compiled into R269 and
``BridgeServer.cs:306`` dispatches op ``inspect-entity-components``; ``call-bridge.ps1``
already fills ``{entityId = $EntityId}`` into the wire request (see its
``if($Operation -ceq 'inspect-entity-components'){ ... $request['entityId']=$EntityId }``
branch) and refuses when ``$EntityId`` is 0. But the op was UNREACHABLE from the queue:

  * ``elevated-request.py`` ``call`` had no ``--entity-id`` flag (only ``--tag-entity-id``),
  * ``elevated-runner.ps1`` ``Get-ValidatedCallArguments`` allowed ONLY
    ``@('kind','runId','op','ids')`` for a generic call, so an ``entityId`` field was
    refused with ``CALL_FIELD_NOT_ALLOWED:entityId``.

The mutation sibling is ``delete-entity-component`` (``EntityComponentDelete.cs``); it ships
four op-owned fields -- ``entityId``, ``action``, ``probeId``, ``componentId`` -- and the
runner narrows a SECOND per-op list for it (``elevated-runner.ps1:266``).

WHAT IT ASSERTS

  a) the ``call`` subparser exposes ``--entity-id`` AND the value reaches the request
     payload under the key ``entityId`` (matching ``call-bridge.ps1``'s ``-EntityId``);
  b) the per-op allowlists are a BEHAVIOUR, so this file lifts the pure validator
     ``Get-ValidatedCallArguments`` out of ``elevated-runner.ps1`` with the PowerShell AST
     and EXECUTES it against a table of untrusted queue bodies -- for the DELETE op, the
     inspect op, and a third op (``node-definitions``). Every accept case asserts the EXACT
     splat key set (the keys the runner splats straight into ``call-bridge.ps1``: the
     ``$callArguments`` keys); every refuse case asserts the exact refusal code.
  c) the DELETE op gates, in particular: an invalid ``action``; ``componentId`` out of the
     int32 range the backend param_shape bounds it to; ``probeId``/``componentId`` refused
     by name on a FOREIGN op; ``entityId``+delete accepted; ``ids``+delete refused.
  d) NEGATIVE CONTROL: a temp copy of the runner with the delete allowlist WIDENED to admit
     ``ids`` flips a case's verdict, and the SAME verification that passes on the real
     runner raises on the mutant -- so the assertion is load-bearing, not incidental.

WHY BEHAVIOUR AND NOT TEXT -- THE BUG THIS FILE NOW GUARDS AGAINST

The previous version scanned the runner SOURCE and asserted that the line *near* each
``$allowedFields=@(...entityId...)`` assignment contained the literal op name. The DELETE
site (``elevated-runner.ps1:266``) is guarded by the FOREIGN op ``delete-entity-component``,
but the assertion passed because the COMMENT one line above it (``elevated-runner.ps1:265``)
literally names ``inspect-entity-components``. Green by incidental text, not by the guard:
the invariant "entityId enters the allowlist only under the inspect op" was satisfied by a
comment, while the DELETE guard named a different op entirely. Reading source cannot pin a
schema; running the validator can. This file runs it.

This file sends NO request. The runner is read as text only for the CLI-plumbing check; its
pure validator is lifted out with the PowerShell parser and run in isolation (b, d); nothing
here dispatches, connects, touches a queue, the helper, the editor or the game.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_component_op_plumbing
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIENT = ROOT / "tools/editor-bridge/elevated-request.py"
RUNNER = ROOT / "tools/editor-bridge/elevated-runner.ps1"

OP = "inspect-entity-components"
OP_DELETE = "delete-entity-component"
OP_NODE = "node-definitions"

#: A well-formed 32-hex runId -- main() only rejects a malformed one; a valid one keeps
#: the refusal reason a MISSING FLAG rather than a bad id.
RUN_ID = "0123456789abcdef0123456789abcdef"

ENTITY_ID = 1234567

#: The EXACT splat key sets ``Get-ValidatedCallArguments`` must return. These are the keys
#: the runner splats into ``call-bridge.ps1`` (``& $callScript @callArguments`` at
#: ``elevated-runner.ps1:954``); a missing or extra key is a real contract change.
ACCEPT_INSPECT = ("keys", ("EntityId", "Operation", "RunId"))
ACCEPT_DELETE = ("keys", ("ComponentAction", "ComponentId", "ComponentProbeId",
                          "EntityId", "Operation", "RunId"))
#: ``componentId`` is added ONLY for ``action='delete'`` (``elevated-runner.ps1:348``).
ACCEPT_DELETE_INSPECT = ("keys", ("ComponentAction", "ComponentProbeId",
                                  "EntityId", "Operation", "RunId"))
#: The ADD sibling shares the delete op's splat keys -- ``call-bridge.ps1`` uses the SAME
#: ``-ComponentAction``/``-ComponentProbeId``/``-EntityId``/``-ComponentId`` parameters for
#: both, and ``componentId`` is added ONLY for ``action='add'``.
ACCEPT_ADD = ACCEPT_DELETE
ACCEPT_ADD_INSPECT = ACCEPT_DELETE_INSPECT
ACCEPT_NODE = ("keys", ("Ids", "Operation", "RunId"))


def _refuse(code: str) -> tuple[str, str]:
    return ("refuse", code)


def _call(body: str) -> str:
    """Wrap field assignments into a validator invocation on a PSCustomObject body."""
    return f"Get-ValidatedCallArguments ([pscustomobject]@{{{body}}})"


#: name -> (validator-body script, expectation). Each body is a fresh untrusted queue body;
#: the validator must ACCEPT it with exactly the named splat keys, or REFUSE it with the
#: named code. ``$run``/``$probeId`` are bound in the probe preamble.
CASES: tuple[tuple[str, str, tuple[str, object]], ...] = (
    # --- inspect (the compiled read op) -------------------------------------------------
    ("inspect-accept",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=5"),
     ACCEPT_INSPECT),
    ("inspect-accept-no-entityid",  # entityId is OPTIONAL here; call-bridge refuses 0
     _call("kind='call';runId=$run;op='inspect-entity-components'"),
     ("keys", ("Operation", "RunId"))),
    ("inspect-refuse-ids",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=5;ids=@(1)"),
     _refuse("CALL_FIELD_NOT_ALLOWED:ids")),
    ("inspect-refuse-entityid-zero",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=0"),
     _refuse("ENTITY_COMPONENT_ID_INVALID")),
    # probeId belongs to the DELETE op; on the inspect op it is a foreign field.
    ("inspect-refuse-foreign-probeid",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=5;probeId=$probeId"),
     _refuse("CALL_FIELD_NOT_ALLOWED:probeId")),
    ("inspect-refuse-foreign-componentid",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=5;componentId=9"),
     _refuse("CALL_FIELD_NOT_ALLOWED:componentId")),
    ("inspect-refuse-foreign-action",
     _call("kind='call';runId=$run;op='inspect-entity-components';entityId=5;action='delete'"),
     _refuse("CALL_FIELD_NOT_ALLOWED:action")),

    # --- delete (the mutation op) -------------------------------------------------------
    ("delete-accept-delete-action",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId=$probeId;componentId=9"),
     ACCEPT_DELETE),
    # A read-only inspect of the component set: NO componentId key in the splat.
    ("delete-accept-inspect-action",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='inspect';probeId=$probeId"),
     ACCEPT_DELETE_INSPECT),
    ("delete-refuse-ids",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId=$probeId;componentId=9;ids=@(1)"),
     _refuse("CALL_FIELD_NOT_ALLOWED:ids")),
    # action invalid / missing.
    ("delete-refuse-action-invalid",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='drop';probeId=$probeId;componentId=9"),
     _refuse("COMPONENT_ACTION_INVALID")),
    ("delete-refuse-action-missing",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "probeId=$probeId;componentId=9"),
     _refuse("COMPONENT_ACTION_INVALID")),
    # componentId is bounded to int32 (the backend param_shape): the max is 2147483647.
    ("delete-refuse-componentid-range",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId=$probeId;componentId=2147483648"),
     _refuse("COMPONENT_ID_INVALID")),
    ("delete-refuse-componentid-missing",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId=$probeId"),
     _refuse("COMPONENT_ID_INVALID")),
    ("delete-refuse-componentid-zero",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId=$probeId;componentId=0"),
     _refuse("COMPONENT_ID_INVALID")),
    ("delete-refuse-probeid-malformed",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';probeId='not-a-32hex-id';componentId=9"),
     _refuse("COMPONENT_PROBE_ID_INVALID")),
    ("delete-refuse-probeid-missing",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=5;"
           "action='delete';componentId=9"),
     _refuse("COMPONENT_PROBE_ID_INVALID")),
    ("delete-refuse-entityid-zero",
     _call("kind='call';runId=$run;op='delete-entity-component';entityId=0;"
           "action='delete';probeId=$probeId;componentId=9"),
     _refuse("ENTITY_COMPONENT_ID_INVALID")),
    ("delete-refuse-entityid-missing",
     _call("kind='call';runId=$run;op='delete-entity-component';"
           "action='delete';probeId=$probeId;componentId=9"),
     _refuse("ENTITY_COMPONENT_ID_INVALID")),

    # --- add (the model-mirror mutation sibling of delete) ------------------------------
    ("add-accept-add-action",
     _call("kind='call';runId=$run;op='add-entity-component';entityId=5;"
           "action='add';probeId=$probeId;componentId=9"),
     ACCEPT_ADD),
    # A read-only inspect of the component set: NO componentId key in the splat.
    ("add-accept-inspect-action",
     _call("kind='call';runId=$run;op='add-entity-component';entityId=5;"
           "action='inspect';probeId=$probeId"),
     ACCEPT_ADD_INSPECT),
    # The add op's action vocabulary is inspect|add -- 'delete' is a foreign action here.
    ("add-refuse-delete-action",
     _call("kind='call';runId=$run;op='add-entity-component';entityId=5;"
           "action='delete';probeId=$probeId;componentId=9"),
     _refuse("COMPONENT_ACTION_INVALID")),
    ("add-refuse-ids",
     _call("kind='call';runId=$run;op='add-entity-component';entityId=5;"
           "action='add';probeId=$probeId;componentId=9;ids=@(1)"),
     _refuse("CALL_FIELD_NOT_ALLOWED:ids")),
    ("add-refuse-componentid-missing",
     _call("kind='call';runId=$run;op='add-entity-component';entityId=5;"
           "action='add';probeId=$probeId"),
     _refuse("COMPONENT_ID_INVALID")),

    # --- a third op: the generic node-query path must be untouched ----------------------
    ("node-accept-ids",
     _call("kind='call';runId=$run;op='node-definitions';ids=@(1,2,3)"),
     ACCEPT_NODE),
    ("node-refuse-entityid",
     _call("kind='call';runId=$run;op='node-definitions';ids=@(1);entityId=7"),
     _refuse("CALL_FIELD_NOT_ALLOWED:entityId")),
    ("node-refuse-probeid",
     _call("kind='call';runId=$run;op='node-definitions';ids=@(1);probeId=$probeId"),
     _refuse("CALL_FIELD_NOT_ALLOWED:probeId")),
    ("node-refuse-componentid",
     _call("kind='call';runId=$run;op='node-definitions';ids=@(1);componentId=9"),
     _refuse("CALL_FIELD_NOT_ALLOWED:componentId")),
    ("node-refuse-no-ids",
     _call("kind='call';runId=$run;op='node-definitions'"),
     _refuse("NODE_QUERY_IDS_REQUIRED")),
)

#: The delete allowlist assignment as it must appear in the runner. The negative control
#: widens a copy of it. The anchor includes the op test as well as the list, because the ADD
#: sibling's list is byte-identical to the delete one -- only the op name makes the site
#: unique (the leading fragment ends at the list's closing ``)`` so ``[:-1]`` still works).
_DELETE_ALLOWLIST = (
    "ceq 'delete-entity-component'){$allowedFields=@('kind','runId','op','entityId','action','probeId','componentId')")

# --- PowerShell AST probe -------------------------------------------------------------
# Lifts the pure validator ``Get-ValidatedCallArguments`` out of the runner and runs it
# against the CASES table. The lift-out is sound because that function is deliberately
# self-contained: it calls no other runner function and reads no script-scope variable
# (see the comment above ``Assert-RequestIdsScope`` in the runner).
_PROBE_HEAD = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile('__RUNNER__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$fn = $ast.Find({ param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -ceq 'Get-ValidatedCallArguments' }, $true)
if ($null -eq $fn) { throw 'MISSING_Get-ValidatedCallArguments' }
. ([scriptblock]::Create($fn.Extent.Text))
$run = '11111111-1111-1111-1111-111111111111'
$probeId = '0123456789abcdef0123456789abcdef'
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


def _powershell_host() -> str | None:
    """pwsh first (what the runner prefers), then the built-in Windows PowerShell."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _build_probe(runner: pathlib.Path, cases) -> str:
    parts = [_PROBE_HEAD.replace("__RUNNER__", str(runner))]
    for name, body, _expect in cases:
        parts.append("Case '%s' { %s }" % (name, body))
    parts.append(_PROBE_TAIL)
    return "\n".join(parts)


def _run_call_probe(runner: pathlib.Path, cases) -> dict:
    """Execute the lifted validator against ``cases`` from ``runner``; return its verdicts.

    Raises ``unittest.SkipTest`` when no PowerShell host is available so the CLI-only
    assertions still run on a host without a shell.
    """
    host = _powershell_host()
    if host is None:
        raise unittest.SkipTest("no PowerShell host (pwsh/powershell) to lift out the validator")
    script = _build_probe(runner, cases)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        [host, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, f"probe host exited {proc.returncode}:\n{proc.stderr}"
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, f"probe produced no stdout (stderr: {proc.stderr})"
    data = json.loads(lines[-1])
    # A single-element array can serialise as a bare string; normalise it back.
    for entry in data.values():
        if entry.get("ok") and isinstance(entry.get("keys"), str):
            entry["keys"] = [entry["keys"]]
    return data


def _load(name: str, relpath: pathlib.Path):
    sibling = str(relpath.parent)
    if sibling not in sys.path:
        sys.path.insert(0, sibling)
    spec = importlib.util.spec_from_file_location(name, relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call_subparser(top: argparse.ArgumentParser) -> argparse.ArgumentParser | None:
    for action in top._actions:  # noqa: SLF001 -- argparse exposes no public walker
        if isinstance(action, argparse._SubParsersAction):
            return action.choices.get("call")
    return None


def _capture_parser(module) -> argparse.ArgumentParser:
    """Build the CLI parser without dispatching: intercept the parse_args call."""
    captured: dict = {}
    original = argparse.ArgumentParser.parse_args

    def spy(self, *args, **kwargs):  # noqa: ANN001
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = spy
    try:
        try:
            module.main()
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = original
    parser = captured.get("parser")
    if parser is None:
        raise AssertionError("main() never reached ArgumentParser.parse_args")
    return parser


class CallSubparserExposesEntityId(unittest.TestCase):
    """(a) --entity-id exists on `call` and lands in the payload as `entityId`."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load("_t_comp_client", CLIENT)

    def test_call_subparser_declares_entity_id(self) -> None:
        parser = _capture_parser(self.module)
        call = _call_subparser(parser)
        self.assertIsNotNone(call, "the CLI has no `call` subparser")
        flags = {opt for action in call._actions for opt in action.option_strings}  # noqa: SLF001
        self.assertIn("--entity-id", flags,
                      "`call` must accept --entity-id to reach op inspect-entity-components")

    def test_entity_id_reaches_the_payload_as_entityId(self) -> None:
        captured: dict = {}

        def fake_send(payload, timeout=None, request_id=None):  # noqa: ANN001
            captured["request"] = dict(payload)
            return {"ok": True, "op": payload.get("op")}

        original_send = self.module.send
        argv = sys.argv
        stderr = sys.stderr
        self.module.send = fake_send
        sys.argv = ["elevated-request.py", "call", "--op", OP,
                    "--entity-id", str(ENTITY_ID), "--run-id", RUN_ID]
        # A missing flag makes argparse print usage before raising; keep the report clean.
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        try:
            try:
                rc = self.module.main()
            except SystemExit as exc:
                self.fail(f"`call` rejected --entity-id (SystemExit {exc.code}); "
                          "the flag does not exist yet")
        finally:
            sys.stderr.close()
            sys.stderr = stderr
            self.module.send = original_send
            sys.argv = argv

        self.assertEqual(rc, 0)
        self.assertEqual(captured["request"].get("entityId"), ENTITY_ID,
                         "the flag must reach the queue payload under the key `entityId`")
        self.assertEqual(captured["request"].get("op"), OP)


class CallValidatorBehaviour(unittest.TestCase):
    """(b)+(c): ``Get-ValidatedCallArguments`` is EXECUTED, not read.

    Every case is a real untrusted queue body; the verdict is whatever the lifted validator
    actually does with it. There is no source-text assertion here to be fooled by a comment.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.results = _run_call_probe(RUNNER, CASES)

    def _verify(self, results: dict) -> None:
        """Raise AssertionError listing every case whose verdict or key set is wrong.

        Deliberately NOT subTest-based: the negative control wraps this in
        ``assertRaises(AssertionError)`` to prove the check is load-bearing, and a
        ``subTest`` context would swallow that exception instead of propagating it.
        """
        problems: list[str] = []
        for name, _body, expect in CASES:
            got = results.get(name)
            if got is None:
                problems.append(f"{name}: the validator reported no verdict")
                continue
            if expect[0] == "refuse":
                code = str(expect[1])
                if got.get("ok"):
                    problems.append(
                        f"{name}: expected refusal `{code}` but the request was ACCEPTED "
                        f"with splat keys {got.get('keys')}")
                elif not str(got.get("error", "")).startswith(code):
                    problems.append(
                        f"{name}: expected refusal `{code}`, got `{got.get('error')}`")
            else:
                keys = tuple(expect[1])
                if not got.get("ok"):
                    problems.append(
                        f"{name}: expected ACCEPT but it was refused: `{got.get('error')}`")
                elif tuple(got.get("keys") or ()) != keys:
                    problems.append(
                        f"{name}: splat key set must be exactly {list(keys)}, "
                        f"got {got.get('keys')}")
        if problems:
            self.fail("validator behaviour mismatch:\n  " + "\n  ".join(problems))

    def test_every_case_matches_its_expected_verdict_and_splat_keys(self) -> None:
        self._verify(self.results)

    def test_delete_op_gates_are_exercised(self) -> None:
        """(c) the DELETE op's own gates, named one by one like the task requires."""
        required = {
            # ids+delete refused
            "delete-refuse-ids": "CALL_FIELD_NOT_ALLOWED:ids",
            # action invalid (and missing)
            "delete-refuse-action-invalid": "COMPONENT_ACTION_INVALID",
            "delete-refuse-action-missing": "COMPONENT_ACTION_INVALID",
            # componentId out of range (and missing / zero)
            "delete-refuse-componentid-range": "COMPONENT_ID_INVALID",
            "delete-refuse-componentid-missing": "COMPONENT_ID_INVALID",
            "delete-refuse-componentid-zero": "COMPONENT_ID_INVALID",
            # probeId invalid / missing
            "delete-refuse-probeid-malformed": "COMPONENT_PROBE_ID_INVALID",
            "delete-refuse-probeid-missing": "COMPONENT_PROBE_ID_INVALID",
            # entityId+delete accepted (and its exact splat key set)
            "delete-accept-delete-action": None,
            # probeId/componentId on a FOREIGN op refused
            "inspect-refuse-foreign-probeid": "CALL_FIELD_NOT_ALLOWED:probeId",
            "inspect-refuse-foreign-componentid": "CALL_FIELD_NOT_ALLOWED:componentId",
            "node-refuse-probeid": "CALL_FIELD_NOT_ALLOWED:probeId",
            "node-refuse-componentid": "CALL_FIELD_NOT_ALLOWED:componentId",
        }
        for name, code in required.items():
            with self.subTest(case=name):
                got = self.results[name]
                if code is None:
                    self.assertTrue(got.get("ok"),
                                    f"{name}: must be ACCEPTED, got `{got.get('error')}`")
                else:
                    self.assertFalse(got.get("ok"),
                                     f"{name}: must be REFUSED `{code}`")
                    self.assertTrue(str(got.get("error", "")).startswith(code),
                                    f"{name}: expected `{code}`, got `{got.get('error')}`")

    def test_delete_splat_key_set_carries_component_id_only_for_the_delete_action(self) -> None:
        """The read action must NOT carry a `ComponentId` key into call-bridge.ps1."""
        delete_keys = tuple(self.results["delete-accept-delete-action"]["keys"])
        inspect_keys = tuple(self.results["delete-accept-inspect-action"]["keys"])
        self.assertIn("ComponentId", delete_keys)
        self.assertNotIn("ComponentId", inspect_keys)
        self.assertEqual(delete_keys, tuple(ACCEPT_DELETE[1]))
        self.assertEqual(inspect_keys, tuple(ACCEPT_DELETE_INSPECT[1]))

    # --- (d) negative control -----------------------------------------------------------
    def test_negative_control_widening_the_delete_allowlist_breaks_this_test(self) -> None:
        """A one-token mutation to a temp copy must FLIP a verdict and fail ``_verify``.

        The mutation re-introduces the exact regression the runner comment warns about:
        appending ``ids`` to the delete per-op list lets an ``ids`` field ride along on
        ``delete-entity-component`` -- which early-returns before the node-query gate. The
        real runner REFUSES that body; the mutant ACCEPTS it. ``_verify``, which passes on
        the real runner, must raise on the mutant.
        """
        # Sanity: the real runner refuses ids on the delete op before we mutate anything.
        self.assertFalse(self.results["delete-refuse-ids"].get("ok"),
                         "precondition: the real runner must refuse ids on delete")

        text = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(text.count(_DELETE_ALLOWLIST), 1,
                         "the delete allowlist site moved -- update the negative control")
        mutated_text = text.replace(
            _DELETE_ALLOWLIST, _DELETE_ALLOWLIST[:-1] + ",'ids')")

        scratch = ROOT / ".runtime" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(dir=scratch))
        try:
            mutant = tmp / "elevated-runner.mutated.ps1"
            mutant.write_text(mutated_text, encoding="utf-8")
            mutated = _run_call_probe(mutant, CASES)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # The widened list lets ids ride along unchecked: the body is now ACCEPTED.
        self.assertTrue(mutated["delete-refuse-ids"].get("ok"),
                        "widening the delete allowlist must let `ids` ride along unchecked")
        # ... and that is precisely the verdict ``_verify`` rejects.
        with self.assertRaises(AssertionError):
            self._verify(mutated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
