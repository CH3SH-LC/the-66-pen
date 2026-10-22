"""Pin: ``testing.FakeBridge``'s bound-graph gate mirrors ``AuthoringGraph.cs`` exactly.

Offline only.  Never touches the bridge, the editor, the game, a save or a queue.  It
reads two source files (the adapter and ``author.py``) and imports the Python mirror.

Why this exists
---------------
``test_bound_graph_readonly.py`` guards the BRIDGE half: exactly one op (``pin-slots``)
is exempt from the bound-graph guard, every write still takes the refusal.  It says, in
its own docstring, that "the Python mirror's own copy of the same rule is deliberately
NOT touched here".

That leaves the mirror free to drift.  And it HAD drifted: ``testing.py``'s ``_edit_gate``
refused ``slots`` on a bound graph (and had no ``_act_slots`` at all), while the bridge had
just been changed to let the read through -- so the fake modelled a refusal the real bridge
does not make, and the demo graph (which IS bound) could not be read in any test.

This file ties the two together: it parses the bridge's exemption OUT OF THE SOURCE and
asserts the Python mirror's permitted set is IDENTICAL.  The names differ by design -- the
mirror dispatches on CLI verbs, the bridge on its action names (``author.py``
``GRAPH_ACTIONS``: ``'slots': 'pin-slots'``) -- so the comparison goes through that same
mapping, and a mapping entry that stops resolving fails loudly rather than comparing
nothing.

Direction policy (which drift is safe)
--------------------------------------
* MORE permissive than the bridge = a **defect**: the fake would model a write the real
  bridge refuses, so a test could pass a sequence the live editor would reject -- false
  confidence in live behaviour.  Unsafe.
* STRICTER than the bridge = also a **drift**: the fake would model a refusal the bridge
  does not make (a capable read modelled as blocked).  On its own that is the *safe* side
  behaviourally -- it fails closed, it cannot let a write through -- but it is still wrong,
  and it is exactly the bug that prompted this file.

The pin therefore asserts EQUALITY, so it fires in BOTH directions; if only one direction
could be chosen, fail-closed (stricter) is the safe side, but neither is accepted here.

Instrument notes (same repo idiom as ``test_bound_graph_readonly.py``)
----------------------------------------------------------------------
Every negative is paired with a same-instrument, same-run POSITIVE CONTROL: the predicate
parse must find a non-empty allowlist containing the known member; the guard must still name
``bind`` and the predicate; and a bound-graph dispatch must actually reach the gate.

Run::

    python -B -m unittest tools.gameplan.tests.test_bound_graph_gate_mirrors_bridge
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

from tools.gameplan.testing import (
    BOUND_GRAPH_ALLOWED,
    REFUSAL_BOUND_GRAPH_EDIT_REFUSED,
    STATUS_SLOTS_READ_ONLY,
    FakeBridge,
)

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_CS = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "AuthoringGraph.cs"
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"

# The bridge predicate that grants the read-only exemption, and the guard it feeds.
_PREDICATE = re.compile(r"static bool AuthorReadOnly\(string action\)\s*=>\s*([^;]+);")
_GUARD = re.compile(r'if\(action!="bind"[^\n]*"AUTHOR_BOUND_GRAPH_EDIT_REFUSED"\)')

# Verbs that reach the bound-graph gate (i.e. NOT the early-return read verbs).  Used to
# prove the mirror still refuses them; behaviour, not a set comparison.
_WRITE_VERBS = ("add", "wire", "value", "set", "condition", "build-plan")


def _load_author():
    """Import ``tools/authoring/author.py`` by path (it has an ``__main__`` guard)."""
    spec = importlib.util.spec_from_file_location("author_gate_mirror", _AUTHOR_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bridge_exempted_actions() -> set[str]:
    """The bridge actions the guard lets through a BOUND graph, parsed from the source.

    = the ``AuthorReadOnly`` allowlist  |  the literal ``bind`` exemption on the guard line.
    """
    if not _ADAPTER_CS.is_file():
        raise AssertionError(f"adapter source missing: {_ADAPTER_CS}")
    src = _ADAPTER_CS.read_text(encoding="utf-8")
    predicate = _PREDICATE.search(src)
    if predicate is None:
        raise AssertionError("AuthorReadOnly predicate not found in the adapter")
    allow = set(re.findall(r'"([a-z0-9-]+)"', predicate.group(1)))
    guard = _GUARD.search(src)
    if guard is None:
        raise AssertionError("bound-graph guard clause not found in the adapter")
    bind = set(re.findall(r'action!="([a-z0-9-]+)"', guard.group(0)))
    return allow | bind


def _expected_mirror_verbs(author) -> set[str]:
    """Map the bridge's exempted actions to the CLI verbs ``FakeBridge`` dispatches on."""
    bridge_to_cli: dict[str, set[str]] = {}
    for cli, bridge in author.GRAPH_ACTIONS.items():
        bridge_to_cli.setdefault(bridge, set()).add(cli)
    expected: set[str] = set()
    unmapped: list[str] = []
    for bridge in _bridge_exempted_actions():
        verbs = bridge_to_cli.get(bridge)
        if not verbs:
            unmapped.append(bridge)
        expected |= verbs or set()
    if unmapped:
        raise AssertionError(
            f"bridge actions with no CLI verb in author.GRAPH_ACTIONS: {sorted(unmapped)} "
            "(a mapping that stopped resolving must not silently compare nothing)"
        )
    return expected


def _argv(action: str, **flags) -> list[str]:
    """A builder-shaped argv: ``graph <cli-verb>`` then ``--k v`` pairs."""
    parts = ["python", "-B", "author.py", "graph", action]
    for key, value in flags.items():
        parts += ["--" + key.replace("_", "-"), str(value)]
    return parts


class TestMirrorMatchesBridge(unittest.TestCase):
    """The mirror's permitted set == the bridge's exemption set, via ``GRAPH_ACTIONS``."""

    @classmethod
    def setUpClass(cls):
        cls.author = _load_author()

    def test_bridge_allowlist_parsed_with_positive_control(self):
        # Instrument sanity: the parse found the known member, not an empty set.
        exempted = _bridge_exempted_actions()
        self.assertIn("pin-slots", exempted)   # the AuthorReadOnly member
        self.assertIn("bind", exempted)        # the guard-line literal

    def test_mapping_resolves_pin_slots_to_the_slots_verb(self):
        # The bridge/mirror names differ; pin the mapping the comparison depends on, so a
        # renamed CLI verb fails HERE (named) rather than silently making the sets equal.
        self.assertEqual(self.author.GRAPH_ACTIONS.get("slots"), "pin-slots")
        self.assertEqual(self.author.GRAPH_ACTIONS.get("bind"), "bind")

    def test_mirror_permitted_set_is_identical_to_the_bridge(self):
        expected = _expected_mirror_verbs(self.author)
        # Positive control: the expected set is non-trivial and carries the read op -- a
        # parse that collapsed to just {"bind"} would make the equality below vacuous.
        self.assertIn("slots", expected)
        self.assertEqual(set(BOUND_GRAPH_ALLOWED), expected,
                         "the Python mirror's bound-graph allowance has drifted from the "
                         "bridge's; more permissive = defect, stricter = still a drift")

    def test_mirror_does_not_grant_anything_the_bridge_refuses(self):
        # The one-directional half stated plainly: every mirror verb is bridge-exempted.
        self.assertTrue(set(BOUND_GRAPH_ALLOWED).issubset(_expected_mirror_verbs(self.author)))


class TestMirrorBehaviourOnABoundGraph(unittest.TestCase):
    """Behaviour, not just the declared set: the gate really lets the read through."""

    ENTITY = 1077936216

    def _bound(self) -> FakeBridge:
        return FakeBridge(bound_entity_id=self.ENTITY)

    def test_slots_is_permitted_on_a_bound_graph(self):
        # THE POINT of the fix.  Before it, this was AUTHOR_ACTION_UNSUPPORTED.
        reply = self._bound()(_argv("slots", request_id="s1", run_id="R", node_id=1))
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["backend"]["status"], STATUS_SLOTS_READ_ONLY)
        self.assertFalse(reply["backend"]["graphModified"])
        self.assertFalse(reply["backend"]["nativeConstructorsInvoked"])

    def test_bind_is_still_permitted_on_a_bound_graph(self):
        reply = self._bound()(_argv("bind", request_id="b1", run_id="R",
                                    entity_id=self.ENTITY, expected_node_count=0))
        self.assertTrue(reply["ok"], reply)

    def test_every_write_verb_is_still_refused_on_a_bound_graph(self):
        bridge = self._bound()
        for action in _WRITE_VERBS:
            with self.subTest(action=action):
                reply = bridge(_argv(action, request_id="w-" + action, run_id="R"))
                self.assertFalse(reply["ok"])
                self.assertIn(REFUSAL_BOUND_GRAPH_EDIT_REFUSED,
                              reply["backend"]["error"])

    def test_an_unbound_graph_permits_the_same_write_verb(self):
        # Positive control on the same instrument: the refusal above is the BOUND state's
        # doing, not a broken handler on its own.
        reply = FakeBridge()(_argv("add", request_id="a1", run_id="R",
                                   definition_id=71, expected_node_count=0, x=0, y=0))
        self.assertTrue(reply["ok"], reply)


if __name__ == "__main__":
    unittest.main()
