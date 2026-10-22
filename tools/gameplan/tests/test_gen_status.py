"""Tests for ``tools/gameplan/gen_status.py`` — the derived status block.

The generator exists because hand-written status tables keep going stale: the
bridge op count moved 136 -> 137 -> 138 in one night and the number had been
copied into roughly two dozen documents.  A generator is only worth anything if a
test proves it *derives* rather than *copies*, so these tests do three things:

  1. **Fresh derivation** — recompute the generator's headline facts by an
     independent parse (own regexes, own walk) and assert the two agree.  If the
     generator ever hardcodes a number, the independent side stops matching.
  2. **Mutation** — feed the generator a deliberately mutated input (a fake
     ``case`` label; a component op removed from the ``ValidateSet``) and assert
     the output **changes**.  A generator that ignores its input would pass (1)
     while still printing a frozen copy; this is the test that fails for it.
  3. **Markdown/JSON agreement** — the two renderings come from one collected
     dict, so they must carry the same numbers, and both must be deterministic
     (no timestamps unless asked).

Read-only and offline: this file reads repo sources and writes only into a
temporary directory for the mutation cases.  It never touches the bridge, the
game, the editor, or the elevated helper.

Run::

    python -B -m unittest tools.gameplan.tests.test_gen_status
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.gameplan import gen_status as gs  # noqa: E402

BRIDGE_SERVER = REPO / "tools" / "editor-bridge" / "ManagedBridge" / "BridgeServer.cs"
CS_PROJ = (REPO / "tools" / "editor-bridge" / "ManagedBridge"
           / "Miliastra.EditorBridge.csproj")
CALL_BRIDGE = REPO / "tools" / "editor-bridge" / "call-bridge.ps1"

# Independent witnesses (deliberately NOT the generator's own compiled regexes, so
# a bug in one side cannot cancel a bug in the other).
_SWITCH_CASE_RE = re.compile(r'case\s+"([A-Za-z0-9][A-Za-z0-9\-]*)"')
_PY_SUITE_RE = re.compile(r"^(test[-_].*|.*_test)\.py$")
_PS_SUITE_RE = re.compile(r"^(test[-_].*|.*[-_]test)\.ps1$")
_FIELD7_USE_RE = re.compile(r"(?<![\"'`])FIELD_TERRAIN_LIST")
_SUITE_PRUNE = {".git", ".runtime", "vendor", "node_modules", "__pycache__",
                ".pytest_cache", ".venv", "venv", "dist", "build", ".idea", ".vscode"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Independent derivations.
# --------------------------------------------------------------------------- #

def fresh_op_count() -> int:
    """Count switch labels by a line-oriented parse (not the generator's regex)."""
    count = 0
    for line in _read(BRIDGE_SERVER).splitlines():
        stripped = line.strip()
        if stripped.startswith('case "'):
            count += 1
    return count


def fresh_component_ops() -> list[str]:
    """Switch labels carrying a ``component`` hyphen-segment, by string splitting."""
    ops = set()
    for line in _read(BRIDGE_SERVER).splitlines():
        stripped = line.strip()
        if not stripped.startswith('case "'):
            continue
        label = stripped.split('"', 2)[1]
        if any(seg.startswith("component") for seg in label.split("-")):
            ops.add(label)
    return sorted(ops)


def fresh_compile_count() -> int:
    return _read(CS_PROJ).count("<Compile Include=")


def fresh_field7_readers() -> list[str]:
    holders = set()
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SUITE_PRUNE and d not in ("bin", "obj")]
        for name in files:
            if not name.endswith(".py") or _PY_SUITE_RE.match(name):
                continue
            text = _read(Path(root) / name)
            if _FIELD7_USE_RE.search(text):
                holders.add((Path(root) / name).relative_to(REPO).as_posix())
    return sorted(holders)


def fresh_suites() -> dict[tuple[str, str], int]:
    suites: dict[tuple[str, str], int] = {}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _SUITE_PRUNE]
        rel = (Path(root).relative_to(REPO).as_posix() if Path(root) != REPO else ".")
        py = sum(1 for n in files if _PY_SUITE_RE.match(n))
        ps = sum(1 for n in files if _PS_SUITE_RE.match(n))
        if py:
            suites[(rel, "python")] = py
        if ps:
            suites[(rel, "powershell")] = ps
    return suites


# --------------------------------------------------------------------------- #
# 1 — fresh derivation.
# --------------------------------------------------------------------------- #

class FreshDerivation(unittest.TestCase):
    """Each test collects and re-derives back-to-back, so the two views of the
    tree are read within microseconds of each other (the repo is a live working
    tree; a wide gap would only measure other writers, not this generator)."""

    def test_op_count_matches_fresh_derivation(self):
        self.assertEqual(
            gs.collect(REPO)["bridge"]["op_count"], fresh_op_count())

    def test_component_ops_match_fresh_derivation(self):
        facts = gs.collect(REPO)
        self.assertEqual(
            [o["op"] for o in facts["bridge"]["component_ops"]],
            fresh_component_ops(),
        )

    def test_compile_count_matches_fresh_derivation(self):
        self.assertEqual(
            gs.collect(REPO)["csproj"]["compile_count"], fresh_compile_count())

    def test_field7_reader_set_matches_fresh_scan(self):
        self.assertEqual(
            gs.collect(REPO)["field7"]["reader_modules"], fresh_field7_readers(),
        )

    def test_suite_counts_match_fresh_discovery(self):
        got = {(s["path"], s["kind"]): s["count"]
               for s in gs.collect(REPO)["tests"]["suites"]}
        self.assertEqual(got, fresh_suites())

    def test_component_ops_carry_all_three_membership_flags(self):
        """Every component op is classified against switch / ValidateSet / DLL."""
        for entry in gs.collect(REPO)["bridge"]["component_ops"]:
            self.assertEqual(
                set(entry), {"op", "in_switch", "in_validateset", "in_dll"})
            self.assertTrue(entry["in_switch"])
            self.assertTrue(entry["in_validateset"])

    def test_dll_membership_matches_the_artifact_on_disk(self):
        """The ``in_dll`` flag is re-checked against the real DLL bytes."""
        facts = gs.collect(REPO)
        d = facts["dll"]
        if not d["present"]:
            self.skipTest("the current payload DLL is not built in this checkout "
                          "(tools/editor-bridge/**/bin/ is git-ignored)")
        blob = (REPO / gs.DLL_DIR_REL / d["name"]).read_bytes()
        for entry in facts["bridge"]["component_ops"]:
            found = (entry["op"].encode("ascii") in blob
                     or entry["op"].encode("utf-16-le") in blob)
            self.assertEqual(entry["in_dll"], found,
                             f"in_dll for {entry['op']} disagrees with the DLL bytes")


# --------------------------------------------------------------------------- #
# 2 — mutation changes the output.
# --------------------------------------------------------------------------- #

class MutationChangesOutput(unittest.TestCase):
    def test_fake_case_label_bumps_the_op_count(self):
        base = gs.collect(REPO)
        src = _read(BRIDGE_SERVER)
        marker = src.index('case "')
        mutated = src[:marker] + 'case "fake-op":\n            ' + src[marker:]
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "BridgeServer.cs"
            fake.write_text(mutated, encoding="utf-8")
            after = gs.collect(REPO, bridge_server=fake)

        self.assertEqual(
            after["bridge"]["op_count"], base["bridge"]["op_count"] + 1,
            "a fake case label did not change the derived op count — the count is copied",
        )
        self.assertIn("fake-op", after["bridge"]["switch_only_ops"])
        self.assertNotEqual(
            gs.render_markdown(after), gs.render_markdown(base),
            "the markdown block did not change when the op set did",
        )

    def test_removing_a_component_op_from_the_validateset_flips_the_flag(self):
        base = gs.collect(REPO)
        self.assertTrue(
            all(o["in_validateset"] for o in base["bridge"]["component_ops"]))
        src = _read(CALL_BRIDGE)
        mutated = src.replace("'delete-entity-component',", "", 1)
        self.assertNotEqual(mutated, src, "the ValidateSet entry was not found to remove")
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "call-bridge.ps1"
            fake.write_text(mutated, encoding="utf-8")
            after = gs.collect(REPO, call_bridge=fake)

        delete = next(o for o in after["bridge"]["component_ops"]
                      if o["op"] == "delete-entity-component")
        self.assertFalse(
            delete["in_validateset"],
            "removing the op from the ValidateSet left the flag true — it is copied",
        )
        # The switch is untouched, so it must stay true.
        self.assertTrue(delete["in_switch"])


# --------------------------------------------------------------------------- #
# 3 — markdown and JSON agree, and both are deterministic.
# --------------------------------------------------------------------------- #

class RenderingsAgree(unittest.TestCase):
    def setUp(self):
        self.facts = gs.collect(REPO)
        self.md = gs.render_markdown(self.facts)
        self.js = json.loads(gs.render_json(self.facts))

    def test_op_count_and_compile_count_agree(self):
        self.assertIn(f"| {self.js['bridge']['op_count']} |", self.md)
        self.assertIn(f"| {self.js['csproj']['compile_count']} |", self.md)

    def test_every_component_op_is_named_in_the_markdown(self):
        for entry in self.js["bridge"]["component_ops"]:
            self.assertIn(f"`{entry['op']}`", self.md)

    def test_every_suite_row_in_markdown_matches_json(self):
        for s in self.js["tests"]["suites"]:
            self.assertIn(f"| `{s['path']}` | {s['kind']} | {s['count']} |", self.md)

    def test_renderings_are_deterministic(self):
        """Pure functions of the collected facts: same input -> byte-identical output."""
        self.assertEqual(gs.render_markdown(self.facts), self.md)
        self.assertEqual(gs.render_json(self.facts), gs.render_json(self.facts))
        self.assertEqual(gs.render_markdown(self.facts, timestamp=False), self.md)

    def test_no_timestamp_unless_asked(self):
        self.assertNotIn("generated at", self.md)
        self.assertNotIn("generated_at", self.js)
        self.assertIn("generated at", gs.render_markdown(self.facts, timestamp=True))
        self.assertIn("generated_at",
                      json.loads(gs.render_json(self.facts, timestamp=True)))

    def test_block_carries_embed_markers(self):
        self.assertTrue(self.md.startswith("<!-- BEGIN GENERATED STATUS BLOCK"))
        self.assertTrue(self.md.rstrip().endswith("<!-- END GENERATED STATUS BLOCK -->"))


class UnknownIsExplicit(unittest.TestCase):
    """An underivable fact is UNKNOWN, never a silent default.

    The generator exists to kill hand-copied numbers; the same bug class returns
    one level up if it prints a value it did not read.  Each case below is a real
    way the tree can make a fact underivable — a missing file, an empty or
    malformed parse, a wrong repo root — and each must surface as an explicit
    ``UNKNOWN`` (with a ``notes`` line), not as 0 / None / [].
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_healthy_repo_emits_no_notes_and_no_unknown(self):
        facts = gs.collect(REPO)
        self.assertEqual(facts["notes"], [], "a healthy tree should raise no notes")
        md = gs.render_markdown(facts)
        self.assertNotIn(gs.UNKNOWN, md)
        # sanity: it really did emit the derived number, not a placeholder
        self.assertIn(f"| {facts['bridge']['op_count']} |", md)

    def test_missing_bridge_server_is_unknown(self):
        facts = gs.collect(REPO, bridge_server=self.tmpdir / "nope.cs")
        self.assertEqual(facts["bridge"]["op_count"], gs.UNKNOWN)
        self.assertEqual(facts["bridge"]["component_ops"], gs.UNKNOWN)
        self.assertEqual(facts["bridge"]["switch_only_ops"], gs.UNKNOWN)
        self.assertIsNone(facts["bridge"]["switch_labels_unique"])
        self.assertIn("| Bridge op count (`BridgeServer.cs` switch labels) | UNKNOWN |",
                      gs.render_markdown(facts))
        self.assertTrue(any("BridgeServer.cs" in n and gs.UNKNOWN in n
                            for n in facts["notes"]))

    def test_zero_case_labels_is_unknown_not_zero(self):
        p = self.tmpdir / "BridgeServer.cs"
        p.write_text("// a dispatch switch with no cases is a parse failure\n",
                     encoding="utf-8")
        facts = gs.collect(REPO, bridge_server=p)
        self.assertEqual(facts["bridge"]["op_count"], gs.UNKNOWN)
        self.assertNotEqual(facts["bridge"]["op_count"], 0)

    def test_malformed_case_label_is_unknown_not_an_undercount(self):
        """A label the strict pattern drops must raise UNKNOWN, not shrink by one."""
        src = _read(BRIDGE_SERVER)
        marker = src.index('case "')
        bad = 'case "Op.With.Dots":\n            '
        p = self.tmpdir / "BridgeServer.cs"
        p.write_text(src[:marker] + bad + src[marker:], encoding="utf-8")
        # the strict pattern silently drops the malformed label ...
        strict = len(gs._CASE_RE.findall(p.read_text(encoding="utf-8")))
        self.assertEqual(
            strict, gs.collect(REPO)["bridge"]["op_count"],
            "fixture failed: the strict pattern was supposed to drop the "
            "malformed label, but it counted it")
        # ... so the emitted fact is UNKNOWN, not the undercounted number.
        facts = gs.collect(REPO, bridge_server=p)
        self.assertEqual(facts["bridge"]["op_count"], gs.UNKNOWN)
        self.assertTrue(any("cannot parse" in n for n in facts["notes"]))

    def test_csproj_without_assembly_name_is_unknown(self):
        cs = _read(CS_PROJ)
        stripped = re.sub(r"^\s*<AssemblyName>.*?</AssemblyName>\s*$", "", cs,
                          flags=re.MULTILINE)
        self.assertNotEqual(stripped, cs, "no <AssemblyName> line was found to strip")
        p = self.tmpdir / "Miliastra.EditorBridge.csproj"
        p.write_text(stripped, encoding="utf-8")
        facts = gs.collect(REPO, csproj=p)
        self.assertEqual(facts["csproj"]["assembly_name"], gs.UNKNOWN)
        self.assertEqual(facts["dll"]["name"], gs.UNKNOWN)
        # present is UNKNOWN (None), NOT a confident "absent": we cannot even
        # name the artifact, so we cannot claim it is missing.
        self.assertIsNone(facts["dll"]["present"])
        md = gs.render_markdown(facts)
        self.assertIn("| csproj payload assembly | `UNKNOWN` |", md)
        self.assertIn("| Current DLL | `UNKNOWN` (UNKNOWN) |", md)

    def test_dll_absent_makes_membership_unknown(self):
        facts = gs.collect(REPO, dll=self.tmpdir / "not-built.dll")
        self.assertFalse(facts["dll"]["present"])
        for entry in facts["bridge"]["component_ops"]:
            self.assertIsNone(entry["in_dll"])
        self.assertTrue(any("DLL" in n for n in facts["notes"]))

    def test_missing_op_validateset_is_unknown_not_the_tagaction_set(self):
        """The file holds a second ValidateSet; renaming the op one must not fall
        back to it (that would emit a confidently-wrong op surface)."""
        src = _read(CALL_BRIDGE)
        mutated = src.replace("ValidateSet('audio-runtime-node-catalog'",
                              "ValidateSetX('audio-runtime-node-catalog'", 1)
        self.assertNotEqual(mutated, src, "the op ValidateSet was not found")
        p = self.tmpdir / "call-bridge.ps1"
        p.write_text(mutated, encoding="utf-8")
        facts = gs.collect(REPO, call_bridge=p)
        self.assertEqual(facts["bridge"]["switch_only_ops"], gs.UNKNOWN)
        self.assertEqual(facts["bridge"]["validateset_only_ops"], gs.UNKNOWN)
        self.assertNotEqual(facts["bridge"]["validateset_only_ops"], ["inspect", "set"],
                            "the $TagAction ValidateSet leaked in as the op surface")
        for entry in facts["bridge"]["component_ops"]:
            self.assertIsNone(entry["in_validateset"])

    def test_no_suites_found_is_unknown(self):
        empty = self.tmpdir / "empty-repo"
        empty.mkdir()
        facts = gs.collect(empty)
        self.assertEqual(facts["tests"]["suites"], gs.UNKNOWN)
        self.assertIn("| Test suites (python) | UNKNOWN |", gs.render_markdown(facts))

    def test_unknown_renders_in_both_markdown_and_json(self):
        facts = gs.collect(REPO, bridge_server=self.tmpdir / "gone.cs")
        md = gs.render_markdown(facts)
        js = json.loads(gs.render_json(facts))
        self.assertIn(gs.UNKNOWN, md)
        self.assertEqual(js["bridge"]["op_count"], gs.UNKNOWN)
        self.assertEqual(js["notes"], facts["notes"])
        self.assertIn("Notes (facts that could not be derived):", md)

    def test_a_wrong_repo_root_blankets_every_fact_as_unknown(self):
        """Pointing --repo-root at an empty dir must not read as "all zeros"."""
        empty = self.tmpdir / "empty-root"
        empty.mkdir()
        facts = gs.collect(empty)
        self.assertEqual(facts["bridge"]["op_count"], gs.UNKNOWN)
        self.assertEqual(facts["csproj"]["compile_count"], gs.UNKNOWN)
        self.assertEqual(facts["csproj"]["assembly_name"], gs.UNKNOWN)
        self.assertEqual(facts["field7"]["reader_modules"], gs.UNKNOWN)
        self.assertEqual(facts["tests"]["suites"], gs.UNKNOWN)
        self.assertTrue(facts["notes"], "an all-unknown block must explain itself")


if __name__ == "__main__":
    unittest.main()
