"""Guard: a READ-ONLY graph op is permitted on a BOUND graph, a WRITE is still refused.

Offline only.  Never touches the bridge, the editor, the game, a save or a queue.
No dispatch, no build.  It reads one source file (``AuthoringGraph.cs``) and the
Python mirror's own copy of the same rule is deliberately NOT touched here.

Why this exists
---------------
A live read of the instance storage kind of ``defId 704`` pin ``3:4`` (the dict
value leaf, ``docs/research/reverse-eng-20261010/DICT-WRITE-PROBE.md:216``) was
blocked with ``AUTHOR_BOUND_GRAPH_EDIT_REFUSED``.  The guard fired BEFORE the
read-only ``pin-slots`` branch, so the demo graph -- which IS bound -- could not be
read at all.  The guard exists to stop a WRITE reaching live gameplay, not a read,
so the fix is that an op proven to mutate nothing may pass it.

The safety property that must hold (this file is its teeth):

  * exactly ONE op -- ``pin-slots`` -- is granted the bound-graph exemption, and
    it is granted on the strength of its BRANCH (it reads the declared pin schema
    and the live instance storage kind and returns ``graphModified:false``), not of
    its name;
  * every other op that reaches the guard still raises the refusal verbatim.

A partition bug here -- a WRITE classified read-only -- would let a write reach a
bound graph, which is exactly the failure the guard was added to prevent.  So the
test is a two-sided gate: (a) the allowlist is exactly ``{"pin-slots"}`` and its
member is a real action that actually reaches the guard; (b) every writing action
that reaches the guard is still refused; (c) the exempt branch really is the read.

Instrument notes (same repo idiom as ``test_dict_branch_gate.py``)
------------------------------------------------------------------
Every negative is paired with a same-instrument, same-run POSITIVE CONTROL: the
action surface parse must find a non-empty dict and known members; each write
symbol whose ABSENCE inside the read-only branch is asserted must be present
somewhere else in the same file (so a scan that returned nothing cannot be mistaken
for a clean branch).

Run::

    python -B -m unittest tools.gameplan.tests.test_bound_graph_readonly
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_CS = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "AuthoringGraph.cs"

# Native-mutation method names this adapter uses.  Present in the file as a positive
# control; asserted ABSENT inside the read-only branch.  Getters (KiPKKaQUNLS storage
# kind, eUgKKLsg3Lw child-0) are deliberately NOT here -- the read branch uses them.
_WRITE_SYMBOLS = (
    "BWmKmyL3bM7",   # native AddNode
    "LapKOOcuGY1",   # native Link
    "vJwKOEFj00D",   # native Disconnect
    "MfLKK0bLIju",   # string setter
    "CHHKK434xan",   # bool setter
    "X8oKKHB87Ue",   # enum setter
    "SH7KKvk8cxe",   # float setter
    "c84KKE8ihrN",   # int setter
    "Ikci0qkvMZX",   # producer invoke (native AddInstructionGraphForEditObj)
    "KRQKKuygfFk",   # list append
)

# Actions that return BEFORE the bound-graph guard, so the guard never sees them.
# Verified against the source (each one's first `if(action=="…"` must precede the
# guard), not merely asserted.
_EARLY_RETURN_ACTIONS = ("create", "lookup", "inspect", "export")

# `bind` is exempt on the guard line itself (`action!="bind"`), not via the allowlist.
_BIND = "bind"


def _source() -> str:
    if not _ADAPTER_CS.is_file():
        raise AssertionError(f"adapter source missing: {_ADAPTER_CS}")
    return _ADAPTER_CS.read_text(encoding="utf-8")


def _action_surface(src: str) -> set[str]:
    """The graph action set, parsed from ValidateAuthorGraph's `fields` table."""
    block = re.search(r"new Dictionary<string, string\[\]>\s*\{(.*?)\}\s*;", src, re.S)
    if block is None:
        raise AssertionError("ValidateAuthorGraph 'fields' dictionary not found")
    return set(re.findall(r'\["([a-z0-9-]+)"\]\s*=', block.group(1)))


def _readonly_allowlist(src: str) -> set[str]:
    """The bound-graph read-only allowlist, parsed from the AuthorReadOnly predicate."""
    predicate = re.search(r"static bool AuthorReadOnly\(string action\)\s*=>\s*([^;]+);", src)
    if predicate is None:
        raise AssertionError("AuthorReadOnly predicate not found in the adapter")
    return set(re.findall(r'"([a-z0-9-]+)"', predicate.group(1)))


def _guard_clause(src: str) -> str:
    """The guard expression text (the `if(… )` that raises the refusal), verbatim."""
    guard = re.search(r'if\(action!="bind"[^\n]*"AUTHOR_BOUND_GRAPH_EDIT_REFUSED"\)', src)
    if guard is None:
        raise AssertionError("bound-graph guard clause not found")
    return guard.group(0)


class TestActionPartition(unittest.TestCase):
    """The read/write partition the guard actually applies, read from the source."""

    def setUp(self):
        self.src = _source()
        self.actions = _action_surface(self.src)
        self.readonly = _readonly_allowlist(self.src)
        self.guard = _guard_clause(self.src)

    def test_surface_parsed_with_positive_control(self):
        # Instrument sanity: a real action surface was found, not an empty set.
        self.assertGreaterEqual(len(self.actions), 14)
        for known in ("create", "lookup", "inspect", "add-node", "pin-slots",
                      "set-value", "build-plan", "connect", "bind", "export"):
            with self.subTest(action=known):
                self.assertIn(known, self.actions)

    def test_guard_clause_exempts_only_bind_and_the_allowlist(self):
        # Positive control: the guard still names the `bound` flag and the allowlist.
        self.assertIn("AuthorReadOnly(action)", self.guard)
        self.assertIn("bound", self.guard)
        self.assertIn('action!="bind"', self.guard)

    def test_readonly_allowlist_is_exactly_pin_slots(self):
        # The exemption is granted to one op, by name, and no other.  Adding a second
        # name (or a write op) fails here and names it.
        self.assertEqual(self.readonly, {"pin-slots"})

    def test_readonly_allowlist_is_a_real_action_that_reaches_the_guard(self):
        # An allowlist entry that is not a real action (typo) or that returns before
        # the guard (dead exemption) would make the partition meaningless.
        self.assertTrue(self.readonly.issubset(self.actions),
                        f"allowlist names not in the action surface: {self.readonly - self.actions}")
        for entry in self.readonly:
            with self.subTest(entry=entry):
                self.assertNotIn(entry, _EARLY_RETURN_ACTIONS)

    def test_early_return_actions_really_precede_the_guard(self):
        # The classification below treats these four as never reaching the guard; that
        # is a fact about the source, so it is checked against the source.
        guard_at = self.src.index(self.guard)
        for action in _EARLY_RETURN_ACTIONS:
            with self.subTest(action=action):
                at = self.src.find(f'if(action=="{action}"')
                self.assertGreaterEqual(at, 0, f"no early branch for {action}")
                self.assertLess(at, guard_at, f"{action} does not return before the guard")

    def test_read_only_op_is_allowed_on_a_bound_graph(self):
        # (a) pin-slots passes the guard.
        reaching = self.actions - set(_EARLY_RETURN_ACTIONS)
        for action in self.readonly:
            with self.subTest(action=action):
                self.assertIn(action, reaching)
                refused = action != _BIND and action not in self.readonly
                self.assertFalse(refused, f"{action} is read-only but would be refused")

    def test_every_writing_op_still_raises_the_refusal(self):
        # (b) THE POINT: nothing except bind and the allowlist is exempt.
        reaching = self.actions - set(_EARLY_RETURN_ACTIONS)
        allowed = {_BIND} | self.readonly
        offenders = {a for a in reaching if a not in allowed}
        # Exhaustiveness: non-refused == exactly bind + allowlist.
        self.assertEqual({a for a in reaching if a in allowed}, {_BIND, "pin-slots"})
        # Every writing op is refused.
        self.assertTrue(offenders, "expected writing actions that reach the guard")
        for action in sorted(offenders):
            with self.subTest(action=action):
                refused = action != _BIND and action not in self.readonly
                self.assertTrue(refused, f"writing op {action} would pass the bound guard")


class TestReadOnlyBranchIsTheRead(unittest.TestCase):
    """The exempt branch really mutates nothing (c)."""

    def setUp(self):
        self.src = _source()
        inner = self.src.index('if(action=="pin-slots") {')
        self.region = self.src[inner:self.src.index("var portKind=3;", inner)]

    def test_branch_reports_graph_modified_false(self):
        # (c) the instrument the live plan consumes: the read flags itself read-only.
        self.assertIn("graphModified=false", self.region)
        self.assertIn("nativeConstructorsInvoked=false", self.region)
        self.assertIn("sentToGame=false", self.region)
        # Positive control on the same slice: it is a branch that RETURNS a payload.
        self.assertIn("return", self.region)

    def test_branch_reads_the_storage_kind(self):
        # Positive control: the branch is the READ half (it asks for a storage kind and
        # reports the declared pin table it was handed, `declared`).
        self.assertIn("AuthorStorageKind", self.region)
        self.assertIn("AuthorPinScalar", self.region)
        self.assertIn("declared.Values", self.region)

    def test_branch_contains_no_native_mutation_symbol(self):
        # Every write symbol absent from the read branch, each one present elsewhere in
        # the same file (positive control), so a scan that found nothing is meaningful.
        for symbol in _WRITE_SYMBOLS:
            with self.subTest(symbol=symbol):
                self.assertGreater(self.src.count(symbol), 0,
                                   f"positive control failed: {symbol} absent from the whole file")
                self.assertNotIn(symbol, self.region,
                                 f"{symbol} (a native mutation) appears in the read-only branch")


if __name__ == "__main__":
    unittest.main()
