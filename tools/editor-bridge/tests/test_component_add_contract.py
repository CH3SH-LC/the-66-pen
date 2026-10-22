#!/usr/bin/env python3
"""Pin the ``add-entity-component`` REQUEST ENVELOPE, the kernel decision, the lease, and the
response contract -- all offline, with no editor and no request.

WHY THIS FILE EXISTS

``EntityComponentAdd.EntityComponentAdd`` is reachable from the elevated queue, so the FIRST
thing that must be right is which request shapes it accepts and what it does with them:

  * envelope (``ValidateEntityComponentAdd``, mirroring ``ValidateEntityComponentDelete``): a
    closed allowlist -- ``{id, op, nonce, action, probeId, entityId}`` and ``componentId`` ONLY
    when ``action == "add"``. Unknown or duplicate fields, a foreign ``action``, a malformed
    ``probeId``, a zero ``entityId``, a zero ``componentId``, and a ``componentId`` above the
    int32 ceiling are all refused BY NAME, before any reflection runs.
  * kernel: ``(before[], componentId) -> ACCEPTED | COMPONENT_ADD_ALREADY_PRESENT`` -- adding an
    id already present is a de-duplication refusal, not a silent second row.
  * lease: one dispatch per ``(probeId, entityId, componentId)`` triplet, at most 16 per run.
  * response contract: the ADD reply MUST carry ``nativeMutationInvoked = false`` and
    ``localModelWritten = true`` and MUST NOT claim ``sentToGame = true``. This op writes the
    editor's LOCAL mirror only; it dispatches no native command and cannot persist. The
    assertion is source-fidelity so a future "just make it true" edit reddens this test.

HOW IT TESTS WITHOUT AN EDITOR

The envelope needs a live editor to actually run, so -- like the sibling gate tests -- the
pure logic is transcribed into Python and driven with synthetic JSON, and every case asserts a
NAMED code (or ACCEPTED). A duplicate-field case is representable because the request is
modelled as an ORDERED LIST of (key, value) pairs, the same way ``JsonElement.EnumerateObject``
sees the wire body. The response/const/csproj checks are source- and build-fidelity on the two
files. Nothing here starts, contacts or injects into any process.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_component_add_contract
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ADD_SRC = ROOT / "tools/editor-bridge/Adapter/EntityComponentAdd.cs"
CSPROJ = ROOT / "tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj"

ACCEPTED = "ACCEPTED"
SUCCESS_STATUS = "entity-component-added-editor-model-only"

PROBE_ID = "0123456789abcdef0123456789abcdef"   # a well-formed Guid "N" string
ENTITY_ID = 999
COMPONENT_ID = 704
INT32_MAX = 2147483647


class Refusal(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------------------
# Envelope: a runnable transcription of ValidateEntityComponentAdd (EntityComponentAdd.cs).
# The body is an ORDERED list of (key, value) pairs, mirroring JsonElement.EnumerateObject.
# ---------------------------------------------------------------------------------------

def validate_envelope(pairs: list[tuple[str, object]]) -> str:
    def S(key: str) -> str:
        for k, v in pairs:
            if k == key and isinstance(v, str):
                return v
        raise Refusal("COMPONENT_REQUIRED_STRING:" + key)

    def U(key: str) -> int:
        for k, v in pairs:
            if k == key and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xFFFFFFFF and v != 0:
                return v
        raise Refusal("COMPONENT_REQUIRED_UINT:" + key)

    action = S("action")
    if action not in ("inspect", "add"):
        raise Refusal("COMPONENT_ACTION_UNSUPPORTED")
    allowed = {"id", "op", "nonce", "action", "probeId", "entityId"}
    if action == "add":
        allowed.add("componentId")
    seen: set[str] = set()
    for k, _ in pairs:
        if k not in allowed or k in seen:
            raise Refusal("COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:" + k)
        seen.add(k)
    if not re.fullmatch(r"[0-9a-fA-F]{32}", S("probeId")):
        raise Refusal("COMPONENT_PROBE_ID_INVALID")
    U("entityId")
    if action == "add" and U("componentId") > INT32_MAX:
        raise Refusal("COMPONENT_ID_OUTSIDE_INT32")
    return ACCEPTED


def _add_body(**over: object) -> list[tuple[str, object]]:
    body: dict[str, object] = {"id": "a" * 32, "op": "add-entity-component", "nonce": "n",
                               "action": "add", "probeId": PROBE_ID,
                               "entityId": ENTITY_ID, "componentId": COMPONENT_ID}
    body.update(over)
    return list(body.items())


def _inspect_body(**over: object) -> list[tuple[str, object]]:
    body: dict[str, object] = {"id": "a" * 32, "op": "add-entity-component", "nonce": "n",
                               "action": "inspect", "probeId": PROBE_ID, "entityId": ENTITY_ID}
    body.update(over)
    return list(body.items())


def _with_extra(base, extra_pair) -> list[tuple[str, object]]:
    return list(base) + [extra_pair]


#: name -> (builder, expected verdict). Each expected verdict is a NAMED code or ACCEPTED.
ENVELOPE_CASES: dict[str, tuple[object, str]] = {
    "add-accept": (_add_body, ACCEPTED),
    "inspect-accept": (_inspect_body, ACCEPTED),
    "add-accept-max-int32": (lambda: _add_body(componentId=INT32_MAX), ACCEPTED),

    "refuse-action-unsupported":
        (lambda: _add_body(action="delete"), "COMPONENT_ACTION_UNSUPPORTED"),
    "refuse-action-missing":
        (lambda: [p for p in _add_body() if p[0] != "action"], "COMPONENT_REQUIRED_STRING:action"),

    "refuse-unknown-field":
        (lambda: _with_extra(_add_body(), ("bogus", 1)), "COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:bogus"),
    "refuse-duplicate-field":
        (lambda: _with_extra(_add_body(), ("entityId", 1)), "COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:entityId"),
    # componentId is admitted ONLY for action=add: on an inspect body it is foreign.
    "refuse-inspect-carries-componentid":
        (lambda: _with_extra(_inspect_body(), ("componentId", COMPONENT_ID)),
         "COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:componentId"),

    "refuse-probeid-malformed":
        (lambda: _add_body(probeId="not-a-32hex-id"), "COMPONENT_PROBE_ID_INVALID"),
    "refuse-probeid-missing":
        (lambda: [p for p in _add_body() if p[0] != "probeId"], "COMPONENT_REQUIRED_STRING:probeId"),

    "refuse-entityid-zero":
        (lambda: _add_body(entityId=0), "COMPONENT_REQUIRED_UINT:entityId"),
    "refuse-entityid-missing":
        (lambda: [p for p in _add_body() if p[0] != "entityId"], "COMPONENT_REQUIRED_UINT:entityId"),

    "refuse-componentid-zero":
        (lambda: _add_body(componentId=0), "COMPONENT_REQUIRED_UINT:componentId"),
    "refuse-componentid-missing":
        (lambda: [p for p in _add_body() if p[0] != "componentId"], "COMPONENT_REQUIRED_UINT:componentId"),
    "refuse-componentid-outside-int32":
        (lambda: _add_body(componentId=INT32_MAX + 1), "COMPONENT_ID_OUTSIDE_INT32"),
}


# ---------------------------------------------------------------------------------------
# Kernel + lease: the pure decisions the adapter makes AFTER the envelope has passed.
# ---------------------------------------------------------------------------------------

def kernel(before: list[int], component_id: int) -> str:
    """EntityComponentAdd's de-dup clause: ``if (before.Contains(componentId))`` -> refuse."""
    if component_id in before:
        raise Refusal("COMPONENT_ADD_ALREADY_PRESENT")
    return ACCEPTED


def lease(attempts: set[str], triplet: str) -> str:
    """The add lease (EntityComponentAdd.cs): triplet repeat -> ALREADY_ATTEMPTED; >= 16 -> limit."""
    if triplet in attempts:
        raise Refusal("COMPONENT_ADD_ALREADY_ATTEMPTED")
    if len(attempts) >= 16:
        raise Refusal("COMPONENT_LEASE_MUTATION_LIMIT")
    attempts.add(triplet)
    return ACCEPTED


KERNEL_CASES = {
    "absent-id-accepted": ([1, 2, 3], 704, ACCEPTED),
    "present-id-refused": ([1, 704, 3], 704, "COMPONENT_ADD_ALREADY_PRESENT"),
    "present-once-refused": ([704], 704, "COMPONENT_ADD_ALREADY_PRESENT"),
}


class EnvelopeBehaviour(unittest.TestCase):
    def test_every_envelope_case_yields_its_named_verdict(self) -> None:
        for name, (builder, expected) in ENVELOPE_CASES.items():
            with self.subTest(case=name):
                try:
                    got = validate_envelope(builder())
                except Refusal as refusal:
                    got = refusal.code
                self.assertEqual(got, expected, f"{name}: expected {expected}, got {got}")

    def test_component_id_is_bounded_only_for_the_add_action(self) -> None:
        """The int32 ceiling is an ADD-action rule; it never runs on the inspect action."""
        self.assertEqual(validate_envelope(_inspect_body()), ACCEPTED)


class KernelAndLeaseBehaviour(unittest.TestCase):
    def test_kernel_cases(self) -> None:
        for name, (before, cid, expected) in KERNEL_CASES.items():
            with self.subTest(case=name):
                try:
                    got = kernel(list(before), cid)
                except Refusal as refusal:
                    got = refusal.code
                self.assertEqual(got, expected)

    def test_triplet_repeat_is_refused(self) -> None:
        attempts: set[str] = set()
        self.assertEqual(lease(attempts, "p:1:704"), ACCEPTED)
        with self.assertRaises(Refusal) as ctx:
            lease(attempts, "p:1:704")
        self.assertEqual(ctx.exception.code, "COMPONENT_ADD_ALREADY_ATTEMPTED")

    def test_seventeenth_distinct_triplet_hits_the_lease_limit(self) -> None:
        attempts: set[str] = set()
        for i in range(16):
            self.assertEqual(lease(attempts, f"p:{i}:704"), ACCEPTED)
        with self.assertRaises(Refusal) as ctx:
            lease(attempts, "p:16:704")
        self.assertEqual(ctx.exception.code, "COMPONENT_LEASE_MUTATION_LIMIT")


# ---------------------------------------------------------------------------------------
# Source + build fidelity: the response contract, the new symbol, and the csproj wiring.
# ---------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


ADD_N = _norm(ADD_SRC.read_text(encoding="utf-8"))
CSPROJ_N = _norm(CSPROJ.read_text(encoding="utf-8"))


class SourceAndBuildFidelity(unittest.TestCase):
    def test_envelope_codes_are_all_present_in_the_source(self) -> None:
        for code in ("COMPONENT_ACTION_UNSUPPORTED", "COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:",
                     "COMPONENT_PROBE_ID_INVALID", "COMPONENT_ID_OUTSIDE_INT32",
                     "COMPONENT_REQUIRED_STRING:", "COMPONENT_REQUIRED_UINT:"):
            with self.subTest(code=code):
                self.assertIn(code, ADD_N, f"the add envelope no longer raises `{code}`")
        self.assertIn(
            'var allowed = new HashSet<string> { "id", "op", "nonce", "action", "probeId", "entityId" };',
            ADD_N, "the base allowlist changed")

    def test_kernel_and_lease_codes_are_present(self) -> None:
        for code in ("COMPONENT_ADD_ALREADY_PRESENT", "COMPONENT_ADD_ALREADY_ATTEMPTED",
                     "COMPONENT_LEASE_MUTATION_LIMIT"):
            with self.subTest(code=code):
                self.assertIn(code, ADD_N)

    def test_the_one_new_symbol_is_a_typed_const_pointing_at_the_ADD_method(self) -> None:
        """The ADD method symbol must be the typed 71 const with the harvested name, so a
        wrong value fails only this op -- never the whole bridge (profile is NOT touched)."""
        self.assertIn('const string ComponentAddMethod71 = "G2GXLQZkPlk";', ADD_N)
        # A profile edit would show up as a BindingContract / symbol-table entry in this file.
        self.assertNotIn("BindingContract(", ADD_N,
                         "the op must add no binding PROFILE contract -- the ADD symbol is a const")
        self.assertNotIn("LegacySymbols", ADD_N)

    def test_the_add_method_is_resolved_with_the_component_bool_signature(self) -> None:
        self.assertIn(
            "contract.CollectionType.GetMethod(ComponentAddMethod71, "
            "BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly, "
            "null, new[] { contract.ComponentType, typeof(bool) }, null);", ADD_N,
            "the ADD method must be resolved by name AND by its (component, bool) signature")

    def test_the_ctor_is_resolved_at_run_time_and_shape_checked(self) -> None:
        self.assertIn("contract.ComponentType.GetConstructor(", ADD_N)
        self.assertIn("COMPONENT_ADD_CTOR_MISSING", ADD_N)

    def test_response_contract_is_local_model_only(self) -> None:
        """The ADD reply must be honest: no native mutation, a local write, no game, no
        persistence. These are the design's pinned booleans (ADD-COMPONENT-OP-DESIGN.md).
        The READ-ONLY inspect sibling legitimately carries the opposite booleans, so the
        assertion is scoped to the ADD return body (from its status literal onward)."""
        add_returns = ADD_N[ADD_N.index('status = "entity-component-added-editor-model-only"'):]
        self.assertIn("nativeMutationInvoked = false", add_returns)
        self.assertIn("localModelWritten = true", add_returns)
        self.assertIn("sentToGame = false", add_returns)
        self.assertIn("persistentSaveVerified = false", add_returns)
        # A future "make it true" edit must redden THIS test.
        self.assertNotIn("sentToGame = true", add_returns)
        self.assertNotIn("nativeMutationInvoked = true", add_returns)

    def test_inspect_sibling_stays_read_only(self) -> None:
        """The other action of this op is a pure read and must keep saying so."""
        inspect_returns = ADD_N[ADD_N.index('status = "entity-components-editor-model-read-only"'):]
        inspect_returns = inspect_returns[:inspect_returns.index("var componentId")]
        self.assertIn("nativeMutationInvoked = false", inspect_returns)
        self.assertIn("localModelWritten = false", inspect_returns)

    def test_the_op_dispatches_no_native_command(self) -> None:
        """The whole point of route A: the add is a local-model write, NOT a native command.
        The native dispatcher and the delete service string must not appear in this file."""
        self.assertNotIn("Ikci0qkvMZX", ADD_N, "the add op must not call the native dispatcher")
        self.assertNotIn("beyondEditObjService", ADD_N, "the add op must not name a native service")

    def test_csproj_compiles_the_new_file(self) -> None:
        self.assertIn('<Compile Include="../Adapter/EntityComponentAdd.cs" Link="EntityComponentAdd.cs" />',
                      CSPROJ_N, "a new Adapter file not in the explicit <Compile> list will not build")


if __name__ == "__main__":
    unittest.main(verbosity=2)
