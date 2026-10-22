"""Guard: the dict (``serverParamType 27``) branch's child-1 accessor -- pinned on the
**recovered 7.1 names**, i.e. the route a future registrar would actually use.

Offline only.  Never touches the bridge, the editor, the game or a save.  No dispatch.

Why this file exists (and how it differs from ``test_dict_branch_gate.py``)
---------------------------------------------------------------------------
``test_dict_branch_gate.py`` keys its gate on the **resolved-corpus** spellings of the
value object's child-1 accessor (``XnwKKQKmI5G`` / ``A96KKPcRCdJ`` / ``FYGKKitKUbh``).
Those are the names under which the code was *found*, not the names the editor exports.

The 2026-10-12 wave recovered the **7.1 real names** of the same members by direct
observation against the pinned build (``.runtime/scratch/DICT-BRANCH-STATUS.md`` section 1;
live ``BeyondEditor.dll`` sha256 ``565dda11...678a`` == the pin, corpus ``resolved-565dda11``):

    value object child-1 : ``q6cXkL8eycl``   (byte-identical sibling ``JdGXkaIkEx5``)
    descriptor  child-1  : ``aV9XHtBZ5tN``   (byte-identical sibling ``XLEXHCe2HFt``)

A registrar therefore inserts / looks for THOSE strings -- either in
``EditorBindingProfile.Generated.cs`` (as a map value, or a ``BindingContract`` member
line) or as a typed 71 const in the adapter source, house style (``EntityComponentAdd.cs``
``ComponentAddMethod71 = "G2GXLQZkPlk"``).  The older guard sees neither route: it looks
only for the corpus spellings, which will never appear once the real name is known.

So this file pins the *same* invariant on the route that matters:

    if ANY payload layer accepts a ``dict`` value tag, these recovered child-1 names
    MUST already be registered (in the profile, or as an adapter const).

On 2026-10-12 the names ARE registered in ``EditorBindingProfile.Generated.cs`` (the map
at ``:537``/``:538``/``:452`` and the contracts at ``:851``/``:852``/``:767``), so the
rule's consequent is now TRUE -- while the ``dict`` TAG stays refused everywhere, so the
antecedent is still false.  The plain ABSENCE assertions below were the ones a registrar
had to update deliberately; they now assert the NEW truth for the names that moved, and
keep the one name (the descriptor's sibling) that did not.

Why the gate being shut is enough to keep the tag OUT of the payload layers (it is not
about the symbol alone): the design's load-bearing premise -- a live concrete-27 pin's
value object carrying storage kind 10003 -- is unobserved, and the best live proxy
diverges (spt-1 Entity reads 0, not 1; no live read ever produced a 10000-series code).
No offline test can settle that.  A tag accepted by the payload and never completable by
the bridge is the hollow capability the pay-layer brief forbids.
"""

import importlib.util
import unittest
from pathlib import Path

from tools.gameplan import paramtypes, plan

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_DIR = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter"
_PROFILE_CS = _ADAPTER_DIR / "EditorBindingProfile.Generated.cs"
_ADAPTER_CS = _ADAPTER_DIR / "AuthoringGraph.cs"
_COMPONENT_ADD_CS = _ADAPTER_DIR / "EntityComponentAdd.cs"  # the typed-71-const idiom
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"

# The recovered 7.1 real names of the four child-1 members (value + descriptor, each with
# a byte-identical sibling).  The first THREE are registered in the profile; the
# descriptor's sibling ``XLEXHCe2HFt`` (7.1 corpus ``:995``, verified present in the pinned
# build) is deliberately NOT registered.  That is a DECISION, not an omission -- the trace:
#
#   * the registered target set is exactly 1:1 with the registered LEGACY keys.  The value
#     object had TWO legacy child-1 spellings (``XnwKKQKmI5G`` / ``A96KKPcRCdJ``), so it
#     needs two targets (``:537``/``:538``, contracts ``:851``/``:852``); the descriptor had
#     one useful legacy key (``oRlK7UMaIYn``, in ``LegacySymbols`` at ``:133``, mapped at
#     ``:452``), so it needs one target (contract ``:767``).  Registering the descriptor's
#     second sibling would be symmetric-looking AND redundant.
#   * an unregistered sibling CANNOT cause a silent WRONG resolution, from the code:
#     ``EditorBindingProfile.ResolveInProfile`` is an exact ``Symbols.TryGetValue`` lookup --
#     there is no nearest-match and every miss is a hard throw (``REQUIRED_BINDING_MISSING``
#     / ``UNREGISTERED_SYMBOL``, ``Fail`` -> ``InvalidOperationException``).  And
#     ``ValidateContract`` (``BindingKind.Method``) selects ``GetMethods().Where(m => m.Name
#     == member)`` BEFORE matching the signature -- an exact-name match, so a contract for
#     ``aV9XHtBZ5tN`` can never silently bind ``XLEXHCe2HFt``.  Neither site chooses among
#     candidates.
#   * the pair is interchangeable anyway: both ``aV9XHtBZ5tN`` (``:970``) and ``XLEXHCe2HFt``
#     (``:995``) are ``vamPAss8BQY(this, 1, ...)`` -- the SAME child index 1 -- so even a
#     hypothetical swap would yield the same child, never a different one.
#
# The ``assertNotIn`` below PINS this decision: registering the sibling would flip it, and
# the test would then have to be reopened deliberately.  (The value object's second sibling
# is usable *because* its second legacy key is registered; the descriptor has no such key.)
RECOVERED_CHILD_ONE = ("q6cXkL8eycl", "JdGXkaIkEx5", "aV9XHtBZ5tN", "XLEXHCe2HFt")
REGISTERED_RECOVERED = ("q6cXkL8eycl", "JdGXkaIkEx5", "aV9XHtBZ5tN")
STILL_ABSENT_RECOVERED = ("XLEXHCe2HFt",)
# Positive controls on the SAME instrument: the registered child-0 siblings (legacy and
# 7.1 actual) and the descriptor's registered child-0 actual.
REGISTERED_CONTROLS = ("eUgKKLsg3Lw", "fPpXkwLeLOm", "Ov2K7oYGvHi", "rKlXHia7SDm")


def _load_author():
    """Import ``tools/authoring/author.py`` by path (it has an ``__main__`` guard)."""
    spec = importlib.util.spec_from_file_location("author_dict_recovered_gate", _AUTHOR_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"expected source file missing: {path}")
    return path.read_text(encoding="utf-8")


class TestRecoveredChildOneGate(unittest.TestCase):
    """Static read of the shipped sources; nothing here is ever executed or dispatched."""

    @classmethod
    def setUpClass(cls):
        cls.profile = _text(_PROFILE_CS)
        cls.adapter = _text(_ADAPTER_CS)
        cls.component_add = _text(_COMPONENT_ADD_CS)
        cls.author = _load_author()

    def test_instrument_finds_the_registered_controls(self):
        # Instrument sanity, same file, same run: if these vanish the negatives below
        # would be meaningless (a lookup that found nothing is not "the gate is shut").
        for name in REGISTERED_CONTROLS:
            with self.subTest(name=name):
                self.assertIn(name, self.profile)
        # The adapter does use the typed-71-const idiom for a real 7.1 member name, so
        # the absence of the dict name in the adapter is a deliberate gap, not a style we
        # never use.
        self.assertIn("G2GXLQZkPlk", self.component_add)
        self.assertIn("AUTHOR_VALUE_LIST_INVALID", self.adapter)

    def test_recovered_child_one_names_now_present_in_the_profile(self):
        # FLIPPED 2026-10-12 (STRENGTHENING), route 1: the map AND the BindingContract
        # lines now carry the child-1 accessors, so Resolve() finds them.
        for name in REGISTERED_RECOVERED:
            with self.subTest(name=name):
                self.assertIn(name, self.profile)
        # The descriptor's byte-identical sibling is STILL absent -- deliberately (see the
        # DECISION trace above the constants: the resolver/validator never choose among
        # candidates, so an unregistered sibling cannot silently mis-resolve).  Its truth did
        # NOT change, so its assertion is NOT flipped.
        for name in STILL_ABSENT_RECOVERED:
            with self.subTest(name=name):
                self.assertNotIn(name, self.profile)
        # Positive control: the registered child-0 sibling IS present on this same text.
        self.assertIn("fPpXkwLeLOm", self.profile)

    def test_recovered_child_one_names_carry_no_adapter_const(self):
        # THE GATE, route 2: a "register it, tag it" step could also land as a typed const
        # in the adapter itself (house style). Comments may document a resolved name;
        # only a string literal would bypass the profile's legacy-symbol lookup.
        for name in RECOVERED_CHILD_ONE:
            with self.subTest(name=name):
                self.assertNotIn('"' + name + '"', self.adapter)
        # Positive control: the same instrument finds a real adapter string literal.
        self.assertIn('"AUTHOR_VALUE_LIST_INVALID"', self.adapter)

    def _adapter_value_slots(self):
        import re

        match = re.search(r"AuthorValueSlots\s*=\s*\{([^}]*)\}", self.adapter)
        self.assertIsNotNone(match, "AuthorValueSlots declaration not found in the adapter")
        return {lit.strip().strip('"') for lit in match.group(1).split(",") if lit.strip()}

    def test_payload_layers_do_not_accept_dict_even_though_the_accessors_are_registered(self):
        # THE RULE, keyed on the recovered names -- the spelling the OTHER guard cannot
        # see.  If any payload layer ever accepts a ``dict`` value tag, the child-1
        # accessor must already be registered (profile or adapter const); otherwise the
        # payload would be accepted and the bridge could never complete it.
        accepts_dict = (
            "dict" in self._adapter_value_slots()
            or "dict" in plan._SLOTS
            or "dict" in self.author.AUTHOR_VALUE_SLOTS
            or paramtypes.slot_for(27) is not None
        )
        child_one_registered = any(
            name in self.profile or name in self.adapter for name in RECOVERED_CHILD_ONE
        )
        if accepts_dict:
            self.assertTrue(
                child_one_registered,
                "a dict value tag was accepted but no RECOVERED child-1 accessor "
                "(q6cXkL8eycl / aV9XHtBZ5tN / siblings) is registered in the profile or "
                "carried as an adapter const: the payload would be silently dropped",
            )
        # 2026-10-12: the recovered child-1 names ARE registered now (``child_one_registered``
        # is True), while the ``dict`` TAG is still refused (``accepts_dict`` is False).
        # Asserted in both directions so a reader sees the exact shape of the invariant.
        self.assertTrue(child_one_registered)
        self.assertFalse(accepts_dict)

    def test_author_payload_layer_accepts_dict_and_refuses_malformed_by_name(self):
        # FLIPPED 2026-10-12.  The payload front's own layer (mine): the well-formed dict is
        # now accepted on the SAME call as the list control, and a malformed one is still a
        # named refusal -- the layer never passes a bad value silently.
        self.author.validate_scalar_payload({"dict": [{"key": {"string": "hp"}, "value": {"int": 3}}]})
        # Positive control: the list container IS accepted on the same call.
        self.author.validate_scalar_payload({"list": [{"int": 1}]})
        # A bare scalar (not a pair) is not a legal entry.
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload({"dict": [{"key": {"string": "hp"}}]})
        self.assertIn("AUTHOR_VALUE_DICT_ENTRY_INVALID", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
