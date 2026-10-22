#!/usr/bin/env python3
"""delete-owned-graph-ids must stay fail-closed -- and the new probes must stay inert.

WHY THIS FILE EXISTS

Every recorded attempt to resolve an owned graph id has come back `modelMatched=0`:
2026-10-06 11:24 (candidates 48), 2026-10-06 13:12 (candidates 499) and 2026-10-09 01:23
(candidates 31). The operation has never once succeeded. The counters localise the
failure to the step that matches a node-resolved model against a `Resources()` Kind-9
model by reference identity, which `OwnedGraphDelete.cs` itself asserts as "the same
model objects, not copies".

2026-10-09 added DIAGNOSTICS for that step -- three candidate id extractions, their
readability and whether any of them reaches a Kind-9 id -- so that one live dry-run
decides the replacement predicate instead of a guess. This file pins the two properties
that make that addition safe:

  1. THE DIAGNOSTICS ARE INERT. A probe result may increment a counter and nothing else.
     If a probe ever fed the delete index, this operation would start deleting on an
     inference nobody has measured -- on a user's save.

  2. THE REFUSAL PATH IS UNCHANGED. An id that does not resolve still refuses the WHOLE
     list and invokes no delete; the `MW_` name gate still stands; the id-and-name
     re-read immediately before each delete still stands.

Static assertions only, deliberately: the matching step needs a live editor, so there is
no offline way to execute it. What CAN be checked offline is that the change is additive,
and that is exactly the claim that needs checking.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_owned_graph_delete_contract
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = ROOT / "tools/editor-bridge/Adapter/OwnedGraphDelete.cs"

PROBES = ("ProbeEntityKeyId", "ProbeWrapperKeyId", "ProbeFlatId")


class TestOwnedGraphDeleteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_source_is_present_and_non_trivial(self) -> None:
        self.assertIn("sealed partial class EditorAdapter", self.text)
        self.assertGreater(len(self.text), 4000)

    # -- 2. the refusal path is unchanged -------------------------------------------

    def test_project_name_gate_still_requires_the_mw_prefix(self) -> None:
        self.assertIn('const string OwnedGraphDeleteNamePrefix = "MW_";', self.text)

    def test_any_unresolved_id_refuses_the_whole_list(self) -> None:
        """The fail-closed property: one bad id deletes nothing at all."""
        self.assertIn('status = "refused-unresolved-ids"', self.text)
        # The refusal must be reached before the delete loop, not after a partial pass.
        refusal = self.text.index('status = "refused-unresolved-ids"')
        delete_loop = self.text.index("foreach (var (id, resource, name) in resolved)")
        self.assertLess(refusal, delete_loop,
                        "the unresolved refusal must precede the delete loop")

    def test_delete_is_still_re_read_and_name_checked_immediately_before(self) -> None:
        self.assertIn('"OWNED_GRAPH_TARGET_CHANGED_DURING_PREPARATION"', self.text)
        # The re-read compares BOTH the id and the stored name against what was indexed.
        self.assertIn("freshId != id || freshName != name", self.text)
        self.assertIn("freshName ?? \"\"", self.text)

    def test_graph_resource_accessor_and_identity_are_used_for_both_reads(self) -> None:
        self.assertEqual(self.text.count('B("SRFKBNXKB02")'), 2)
        self.assertIn('string resourceField = B("nDdKtzI6RIf");', self.text)
        self.assertIn("graphResourceNodeType.IsInstanceOfType(node)", self.text)
        self.assertNotIn("OwnedDeleteWalkRootType", self.text)
        self.assertNotIn("freshId = ReadCrudKey", self.text)
        self.assertIn('Stored(freshModel, B("fLGKbbHeoYG"))', self.text)
        self.assertIn("ReferenceEquals(currentGraphs[0].Model, freshModel)", self.text)

    def test_bound_graph_refuses_before_dispatch_and_is_checked_again(self) -> None:
        self.assertLess(self.text.index('"OWNED_GRAPH_BOUND:"'),
                        self.text.index("foreach (var (id, resource, name) in resolved)"))
        self.assertIn("InstructionGraphBoundEntities(id).Count == 0", self.text)
        self.assertIn('string deleteName = B("zgVKB6OS1MZ");', self.text)
        self.assertNotIn("JkmYibSuDZr.Remove", self.text)

    def test_graph_accessor_has_exact_registered_return_type(self) -> None:
        profile = (ROOT / "tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs").read_text(encoding="utf-8")
        self.assertIn('{ "SRFKBNXKB02", "yosjCRW4uKm" }', profile)
        self.assertIn('new BindingContract("fYiNtsjNFLpjCdRQ3Cvj.snNdG3jNcHxXOpcU0fHG", '
                      '"yosjCRW4uKm", BindingKind.Method, '
                      '"():E8xv5pXu77T6046o5sVM.vUK4LLXuq7BbA0L017eJ", false)', profile)
        # The old entity getter remains a distinct mapping for the entity operations.
        self.assertIn('{ "ndlKBRCbBjF", "ABijCETHXZy" }', profile)

    # -- 1. the diagnostics are inert ------------------------------------------------

    def test_all_three_probes_exist(self) -> None:
        for probe in PROBES:
            self.assertIn(f"uint? {probe}(object model)", self.text,
                          f"{probe} is the extraction the live dry-run needs")

    def test_each_probe_contains_its_own_failure(self) -> None:
        """A field path that does not apply to a model is an expected outcome, not a
        failure: it must return null rather than escape and abort the walk."""
        for probe in PROBES:
            body = re.search(
                rf"uint\? {probe}\(object model\)\s*\{{(.*?)\n    \}}", self.text, re.S)
            self.assertIsNotNone(body, f"{probe} body not found")
            assert body is not None
            self.assertIn("catch (Exception) { return null; }", body.group(1),
                          f"{probe} must swallow its own field-path failure")

    def test_no_probe_result_reaches_the_delete_index(self) -> None:
        """The index is populated only from the reference-identity match. If a probe
        ever gated or fed `index[id] = resource`, this operation would delete on an
        unmeasured inference."""
        guard = self.text.index("if (!graphModels.TryGetValue(model, out uint id)) continue;")
        assign = self.text.index("index[id] = resource;")
        self.assertLess(guard, assign, "the index assignment must sit behind the identity guard")
        between = self.text[guard:assign]
        for probe in PROBES:
            self.assertNotIn(probe, between,
                             f"{probe} must not influence which id is indexed")

    def test_index_has_exactly_one_write_site(self) -> None:
        self.assertEqual(self.text.count("index[id] = resource;"), 1)

    def test_match_diagnostics_are_reported_on_refusal(self) -> None:
        self.assertIn("matchDiagnostics = ownedGraphMatchDiagnostics,", self.text)
        self.assertIn("ownedGraphMatchDiagnostics = new Dictionary<string, object> {", self.text)

    def test_probe_results_are_only_counted(self) -> None:
        """Every use of a probe's value is a counter increment or a diagnostic sample."""
        for probe in PROBES:
            for match in re.finditer(rf"=\s*{probe}\(model\);", self.text):
                line_end = self.text.index("\n", match.start())
                line = self.text[self.text.rindex("\n", 0, match.start()) + 1:line_end]
                self.assertRegex(
                    line.strip(),
                    r"^var \w+ = Probe\w+\(model\);$",
                    f"probe result captured outside a local: {line.strip()}")
        # The locals are then compared against a read-only id set and used for counters.
        self.assertIn("if (kind9Ids.Contains(", self.text)
        self.assertNotIn("resolved.Add((", self.text.split("// Record what this candidate")[0][-400:],
                         "diagnostics must not add to the resolved list")


if __name__ == "__main__":
    unittest.main()
