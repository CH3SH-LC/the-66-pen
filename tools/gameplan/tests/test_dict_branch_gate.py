"""Guard: the dict (serverParamType 27) value branch -- child-1 accessors now registered, tag still refused.

Offline only.  Never touches the bridge, the editor, the game or a save.  No dispatch.

Why this exists (wave 29AV design + 29AW implementation attempt)
----------------------------------------------------------------
``test_dict_value_shape_absent.py`` pins the *payload-shape* half of the dict
negative: no layer has a ``dict`` tag, and each refuses it by name.  That is the
offline half.

This test pins the **other** half -- the link that makes the payload half correct
rather than merely convenient.  A dict constant is written by appending a kv-pair
(10007) entry to the container (10003) and then filling the entry's TWO leaves.
The 7.1 binding profile registers the child accessors by name.  On 2026-10-12 a wave
recovered the real 7.1 names of the child-1 accessors (``.runtime/scratch/
DICT-BRANCH-STATUS.md`` section 1; live ``BeyondEditor.dll`` sha256 ``565dda11...678a``
== the pin, corpus ``resolved-565dda11``) and registered them in the profile:

* value object ``iULKMUX9YXnL8b394xZ8.YMt9KPX9HpgYFteH6uoG``
    - ``eUgKKLsg3Lw()`` -> child 0                       (REGISTERED, pre-existing)
    - ``XnwKKQKmI5G()`` -> child 1 ``q6cXkL8eycl``       (REGISTERED 2026-10-12)
    - ``A96KKPcRCdJ()`` -> child 1 ``JdGXkaIkEx5``       (REGISTERED 2026-10-12, sibling)
    - ``FYGKKitKUbh()`` (generic indexed accessor)       (STILL UNREGISTERED)
* descriptor ``X7NDusXHZZJUhYx2Q1n7.bX3XUOXHOHPd0fXaebqA``
    - ``Ov2K7oYGvHi()`` -> child 0                       (REGISTERED, pre-existing)
    - ``oRlK7UMaIYn()`` -> child 1 ``aV9XHtBZ5tN``       (REGISTERED 2026-10-12)

So the SECOND leaf of a dict entry is now **reachable**: both the map and the
``BindingContract`` lines carry the child-1 accessors, so ``EditorBindingProfile.
Resolve`` no longer fails closed on the two leaves a dict entry needs.

A registered SYMBOL is not the CAPABILITY: the ``dict`` value TAG is still refused
by every payload layer (``TestNoHollowDictTag`` below), so the branch stays shut.
When this symbol WAS unregistered, adding the tag alone would have been a **hollow
capability** -- the payload accepted and silently producing nothing.  That is the
defect the invariant names, and it is strictly worse than the refusal.

The rule this test enforces, one-directionally (so a future "register the symbol
first, tag second" step is *not* a false alarm):

    if ANY layer accepts a ``dict`` value tag, the child-1 accessor MUST be
    registered in the binding profile.

Positive controls on the SAME instrument (the profile file): the child-0
accessors and the container/append/storage-kind symbols the EXISTING list branch
already resolves are asserted PRESENT, so a set of lookups that returned nothing
would not be mistaken for "the gate is closed".

That future wave arrived on 2026-10-12: the real 7.1 child-1 names are registered
(above), so the rule's consequent is now TRUE rather than pending.  The gate-pin
assertions below were updated in the same step -- to assert the NEW truth (the
child-1 accessor RESOLVES) while every TAG refusal stays untouched.
"""

import importlib.util
import re
import unittest
from pathlib import Path

from tools.gameplan import paramtypes, plan

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_CS = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "AuthoringGraph.cs"
_PROFILE_CS = (
    _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "EditorBindingProfile.Generated.cs"
)
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"


def _load_author():
    """Import ``tools/authoring/author.py`` by path (it has an ``__main__`` guard)."""
    spec = importlib.util.spec_from_file_location("author_dict_gate", _AUTHOR_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile_symbols():
    """The registered legacy -> 7.1 name map, parsed straight from the generated profile."""
    if not _PROFILE_CS.is_file():
        raise AssertionError(f"binding profile missing: {_PROFILE_CS}")
    src = _PROFILE_CS.read_text(encoding="utf-8")
    pairs = re.findall(r'\{\s*"([A-Za-z0-9_]+)"\s*,\s*"([A-Za-z0-9_]+)"\s*\}', src)
    return {legacy: actual for legacy, actual in pairs}


class TestBindingProfileGate(unittest.TestCase):
    """Static read of the generated 7.1 binding profile (never executed)."""

    def setUp(self):
        self.symbols = _profile_symbols()

    def test_profile_parsed_with_positive_control(self):
        # Instrument sanity: the parse found a real table, not nothing.
        self.assertGreater(len(self.symbols), 200)

    def test_existing_list_branch_symbols_are_registered(self):
        # POSITIVE CONTROL.  Every symbol the shipped ``AuthorWriteList`` branch already
        # resolves must be present, on this same instrument.  If these ever vanish, the
        # negative assertions below would be meaningless.
        for legacy in ("KiPKKaQUNLS", "KRQKKuygfFk", "Ov2K7oYGvHi", "eUgKKLsg3Lw"):
            with self.subTest(legacy=legacy):
                self.assertIn(legacy, self.symbols)

    def test_child_one_accessor_is_registered_the_gate_is_open(self):
        # FLIPPED 2026-10-12 (STRENGTHENING).  The wave recovered the real 7.1 names and
        # registered the value object's two child-1 accessors, so Resolve() now finds
        # them.  A registered NAME is not the CAPABILITY: the dict TAG stays refused.
        for legacy in ("XnwKKQKmI5G", "A96KKPcRCdJ"):
            with self.subTest(legacy=legacy):
                self.assertIn(legacy, self.symbols)
        # The GENERIC indexed accessor is still unmapped -- its absence is UNCHANGED.
        self.assertNotIn("FYGKKitKUbh", self.symbols)

    def test_descriptor_child_one_accessor_is_registered(self):
        # FLIPPED 2026-10-12 (STRENGTHENING): the descriptor's child-1 accessor is mapped
        # too (``oRlK7UMaIYn`` -> ``aV9XHtBZ5tN``).
        self.assertIn("Ov2K7oYGvHi", self.symbols)     # positive control (child 0)
        self.assertIn("oRlK7UMaIYn", self.symbols)     # child 1 -- now REGISTERED


class TestNoHollowDictTag(unittest.TestCase):
    """The one-directional drift guard: a ``dict`` tag may not exist while the gate is shut."""

    @classmethod
    def setUpClass(cls):
        cls.author = _load_author()

    def _adapter_source(self):
        self.assertTrue(_ADAPTER_CS.is_file(), f"adapter source missing: {_ADAPTER_CS}")
        return _ADAPTER_CS.read_text(encoding="utf-8")

    def _adapter_value_slots(self):
        src = self._adapter_source()
        match = re.search(r"AuthorValueSlots\s*=\s*\{([^}]*)\}", src)
        self.assertIsNotNone(match, "AuthorValueSlots declaration not found in the adapter")
        return {literal.strip().strip('"') for literal in match.group(1).split(",") if literal.strip()}

    def test_dict_is_a_container_not_a_slot(self):
        # UPDATED 2026-10-12, assertions UNCHANGED.  A dict is a container written per entry,
        # exactly like `list`: neither is a value SLOT.  So the slot vocabulary still has no
        # `dict` entry -- `paramtypes.slot_for(27)` is still None -- even though the adapter
        # now carries a `dict` VALUE BRANCH (the set-value / build-plan payload name).
        adapter_slots = self._adapter_value_slots()
        self.assertNotIn("dict", adapter_slots)
        self.assertNotIn("dict", plan._SLOTS)
        self.assertNotIn("dict", self.author.AUTHOR_VALUE_SLOTS)
        self.assertIsNone(paramtypes.slot_for(27))
        # Positive control: the scalar slot set is non-empty on the same instrument.
        self.assertIn("int", adapter_slots)
        self.assertIn("int", self.author.AUTHOR_VALUE_SLOTS)

    def test_dict_tag_may_not_exist_unless_the_child_one_accessor_is_registered(self):
        # THE RULE (name updated 2026-10-12).  If any layer accepts a ``dict`` tag, the
        # bridge must be able to complete it -- i.e. the child-1 accessor must be
        # registered.  Adding the tag alone (the hollow capability) fails here and names
        # the missing link.
        accepts_dict = (
            "dict" in self._adapter_value_slots()
            or "dict" in plan._SLOTS
            or "dict" in self.author.AUTHOR_VALUE_SLOTS
            or paramtypes.slot_for(27) is not None
        )
        child_one_registered = any(
            legacy in _profile_symbols()
            for legacy in ("XnwKKQKmI5G", "A96KKPcRCdJ", "FYGKKitKUbh")
        )
        if accepts_dict:
            self.assertTrue(
                child_one_registered,
                "a dict value tag was accepted but no child-1 accessor is registered in "
                "EditorBindingProfile.Generated.cs: the payload would be silently dropped",
            )
        # 2026-10-12 (later): the dict CAPABILITY landed -- the adapter now carries a `dict`
        # value branch.  The child-1 accessor is registered (the rule's consequent is TRUE),
        # and `accepts_dict` remains FALSE because it keys on the SLOT sets only; the tag the
        # branch accepts is a payload NAME, so the slot-vocabulary invariant still holds.
        self.assertTrue(child_one_registered)
        self.assertFalse(accepts_dict)

    def test_adapter_source_has_the_dict_value_branch(self):
        # FLIPPED 2026-10-12.  Same instrument, same file, same run: known-present literals
        # are the control, and the dict branch is now one of them.
        src = self._adapter_source()
        self.assertIn("AUTHOR_VALUE_TYPE_UNSUPPORTED", src)  # positive control
        self.assertIn("AUTHOR_VALUE_LIST_INVALID", src)      # positive control
        for needle in ('"dict"', "AUTHOR_VALUE_DICT", "AuthorWriteDict"):
            with self.subTest(needle=needle):
                self.assertIn(needle, src)


if __name__ == "__main__":
    unittest.main()
