"""Guard: the type-27 dict *constant* write branch -- the tag landed, the leaves resolve.

Offline only.  Never touches the bridge, the editor, the game or a save.  No dispatch.

This is the positive counterpart of the retired ``test_dict_value_shape_absent`` negative
and of the ``test_dict_branch_gate``/``test_dict_child_one_recovered_gate`` gates.  It pins
the three facts the capability rests on, each on the SAME instrument the negative used:

1. **The adapter carries the branch.**  ``AuthoringGraph.cs`` has a ``case "dict"`` shape
   check (bounded, pair-array, scalar-only leaves, duplicate keys refused), a
   ``AuthorWritePinValue`` dict arm, a ``AuthorWriteDict`` writer, and the ``build-plan``
   value loop routes ``payloadName=="dict"`` to it.

2. **Every symbol the branch calls is registered.**  The branch resolves five legacy names
   through ``B(...)``; each must be present in ``EditorBindingProfile.Generated.cs`` with a
   matching ``BindingContract``.  A missing one is an ``UNREGISTERED_SYMBOL`` at dispatch.
   Positive controls on the same file: the four names the shipped ``AuthorWriteList``
   branch already resolves.

3. **A dict is a container, not a slot.**  ``paramtypes.slot_for(27)`` stays ``None``,
   ``plan._SLOTS`` and ``author.AUTHOR_VALUE_SLOTS`` gain no ``dict``, and ``builder._tagged``
   gains no ``dict`` decoder -- exactly the ``list`` situation.  The tag the adapter accepts
   is a payload NAME, so the slot vocabulary is unchanged.

The invariant the older guards enforced -- "a dict value tag may not exist unless the
child-1 accessor is registered" -- is preserved here as a conjunct: the branch exists AND
the child-1 accessor is registered.
"""

import importlib.util
import re
import unittest
from pathlib import Path

from tools.gameplan import paramtypes, plan
from tools.gameplan.builder import _tagged

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_CS = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "AuthoringGraph.cs"
_PROFILE_CS = (
    _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "EditorBindingProfile.Generated.cs"
)
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"


def _load_author():
    spec = importlib.util.spec_from_file_location("author_dict_write", _AUTHOR_PY)
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


class TestAdapterHasTheDictBranch(unittest.TestCase):
    def setUp(self):
        self.assertTrue(_ADAPTER_CS.is_file(), f"adapter source missing: {_ADAPTER_CS}")
        self.src = _ADAPTER_CS.read_text(encoding="utf-8")

    def test_branch_symbols_are_present_with_positive_control(self):
        # Positive controls on the same file/run: the list branch's own literals.
        for control in ("AUTHOR_VALUE_LIST_INVALID", "AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED"):
            with self.subTest(control=control):
                self.assertIn(control, self.src)
        for needle in (
            'case "dict":',
            "AUTHOR_VALUE_DICT_SHAPE_INVALID",
            "AUTHOR_VALUE_DICT_ENTRY_INVALID",
            "AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED",
            "AUTHOR_VALUE_DICT_DUPLICATE_KEY",
            "AUTHOR_VALUE_NOT_A_DICT",
            "AuthorWriteDict",
            'if(name=="dict")',
            'else if(payloadName=="dict")',
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.src)

    def test_container_kind_assert_matches_the_list_precedent(self):
        # The dict container asserts 10003 the way the list asserts 10002 -- a wrong kind is
        # a refusal, never a silent write into a differently-shaped slot.
        self.assertIn("AuthorStorageKind(list)!=10002", self.src)                  # list control
        self.assertIn("AuthorStorageKind(dict)!=10003", self.src)                  # dict

    def test_the_branch_calls_only_registered_symbols(self):
        # The exact legacy names the branch resolves through B(...).  All five must be in the
        # profile (symbol entry + mapping).  The child-1 name is the one whose absence used to
        # make the capability hollow.
        symbols = _profile_symbols()
        self.assertGreater(len(symbols), 200)  # instrument sanity
        for legacy in (
            "KiPKKaQUNLS",   # container storage kind
            "KRQKKuygfFk",   # append one entry      (also used by AuthorWriteList)
            "Ov2K7oYGvHi",   # descriptor child-0    (also used by AuthorWriteList)
            "eUgKKLsg3Lw",   # entry child-0 = key
            "XnwKKQKmI5G",   # entry child-1 = value (the recovered name)
        ):
            with self.subTest(legacy=legacy):
                self.assertIn(legacy, symbols)


class TestDictIsAContainerNotASlot(unittest.TestCase):
    """Parity with ``list``: a container payload name, never a value slot."""

    @classmethod
    def setUpClass(cls):
        cls.author = _load_author()

    def test_slot_vocabulary_is_unchanged_with_positive_control(self):
        self.assertIsNone(paramtypes.slot_for(27))                 # dict has no slot
        self.assertEqual(paramtypes.slot_for(3), "int")            # positive control
        self.assertNotIn("dict", plan._SLOTS)
        self.assertNotIn("dict", self.author.AUTHOR_VALUE_SLOTS)
        # The list container is absent from both sets too -- the precedent.
        self.assertNotIn("list", plan._SLOTS)
        self.assertNotIn("list", self.author.AUTHOR_VALUE_SLOTS)
        # Positive control: the scalar slots are present on the same sets.
        for slot in ("int", "uint", "enum", "float", "bool", "string"):
            with self.subTest(slot=slot):
                self.assertIn(slot, plan._SLOTS)

    def test_container_facts_are_named_not_slotted(self):
        # The wire kinds are recorded as FACTS, not as a slot mapping.
        self.assertEqual(paramtypes.DICT_CONTAINER_STORAGE, 10003)
        self.assertEqual(paramtypes.DICT_ENTRY_STORAGE, 10007)

    def test_builder_still_has_no_dict_decoder_with_positive_control(self):
        # `builder._tagged` encodes a SCALAR slot only, exactly as it has no `list` decoder.
        with self.assertRaises(ValueError):
            _tagged("dict", {"k": {"int": 1}})
        with self.assertRaises(ValueError):
            _tagged("list", [1])
        self.assertEqual(_tagged("int", 3), '{"int": 3}')          # positive control


class TestDictReferenceKeySafety(unittest.TestCase):
    """Static regression guards for R291's partial-append failure, not native acceptance."""

    @classmethod
    def setUpClass(cls):
        cls.src = _ADAPTER_CS.read_text(encoding="utf-8")

    def test_reference_auto_requires_uint_and_uses_registered_reference_setter(self):
        auto = self.src.split("static string AuthorAutoSlot(int storage", 1)[1].split("// One write", 1)[0]
        pairs = re.findall(r'(\d+) when payloadName=="(\w+)" => "(\w+)"', auto)
        self.assertIn(("2", "int", "int"), pairs)  # established integer control
        self.assertIn(("6", "uint", "enum"), pairs)  # established enum control
        self.assertEqual([p for p in pairs if p[0] == "1"], [("1", "uint", "uint")])
        scalar = self.src.split("object? AuthorWriteScalar(", 1)[1]
        uint_arm = scalar.split('case "uint": {', 1)[1].split('case "int": {', 1)[0]
        self.assertLess(uint_arm.index("AuthorStorageKind(scalar)!=1"), uint_arm.index("setter.Invoke"))
        self.assertIn('B("LhkKKbraAbs")', uint_arm)
        self.assertIn('B("cPOKKedklwd")', uint_arm)
        self.assertIn("is not uint seen || seen!=wanted", uint_arm)
        symbols = _profile_symbols()
        self.assertEqual(symbols["LhkKKbraAbs"], "N6WX98qouJ0")
        self.assertEqual(symbols["cPOKKedklwd"], "BdsXk9NE0ND")

    def test_entire_dict_type_preflight_precedes_any_append(self):
        writer = self.src.split("int AuthorWriteDict(", 1)[1].split("AuthorWriteResult AuthorWritePinValue", 1)[0]
        append = writer.index('B("KRQKKuygfFk")')
        self.assertLess(writer.index("AuthorDeclaredStorage(entryDescriptor)!=10007"), append)
        self.assertLess(writer.index("AuthorDictLeafSlot(keyDescriptor,keyLeaf,leafSlot)"), append)
        self.assertLess(writer.index("AuthorDictLeafSlot(valueDescriptor,valueLeaf,leafSlot)"), append)
        self.assertLess(writer.index("foreach(var pair in entries.EnumerateArray())"), writer.index("foreach(var pair in prepared)"))
        self.assertLess(writer.index("foreach(var pair in prepared)"), append)
        self.assertIn('B("oRlK7UMaIYn")', writer)
        self.assertIn("AUTHOR_VALUE_DICT_LEAF_STORAGE_MISMATCH", writer)
        symbols = _profile_symbols()
        self.assertEqual(symbols["O2EKYx5c6Xs"], "KjpXYIFAqQh")
        self.assertEqual(symbols["oRlK7UMaIYn"], "aV9XHtBZ5tN")

    def test_reference_key_uint32_range_is_checked_before_bridge(self):
        author = _load_author()
        author.validate_scalar_payload({"dict": [{"key": {"uint": 4294967295}, "value": {"int": 10}}]})
        for key in (-1, 4294967296, True):
            with self.subTest(key=key), self.assertRaises(ValueError):
                author.validate_scalar_payload({"dict": [{"key": {"uint": key}, "value": {"int": 10}}]})


class TestAuthorAcceptsTheDictShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.author = _load_author()

    def test_well_formed_dict_is_accepted(self):
        self.author.validate_scalar_payload(
            {"dict": [{"key": {"string": "hp"}, "value": {"int": 3}},
                      {"key": {"string": "mp"}, "value": {"int": 7}}]}
        )
        self.author.validate_scalar_payload({"dict": []})   # empty, parity with {"list": []}

    def test_malformed_shapes_refuse_by_name(self):
        cases = {
            "AUTHOR_VALUE_DICT_SHAPE_INVALID": {"dict": {"k": {"int": 1}}},
            "AUTHOR_VALUE_DICT_ENTRY_INVALID": {"dict": [{"key": {"string": "hp"}}]},
            "AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED": {"dict": [{"key": {"list": [1]}, "value": {"int": 3}}]},
            "AUTHOR_VALUE_DICT_DUPLICATE_KEY": {
                "dict": [{"key": {"string": "hp"}, "value": {"int": 1}},
                         {"key": {"string": "hp"}, "value": {"int": 2}}]
            },
        }
        for expected, payload in cases.items():
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as ctx:
                    self.author.validate_scalar_payload(payload)
                self.assertIn(expected, str(ctx.exception))

    def test_a_list_of_dicts_is_still_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload({"list": [{"dict": {"int": 1}}]})
        self.assertIn("AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
