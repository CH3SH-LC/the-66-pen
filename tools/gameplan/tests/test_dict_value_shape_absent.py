"""Guard: a dict (serverParamType 27) *constant*'s payload shape.

Offline only.  Never touches the bridge, the editor, the game or a save.

SUPERSEDED 2026-10-12 (see the flipped tests below)
---------------------------------------------------
This module used to assert a NEGATIVE: no layer carried a ``dict`` tag, so a dict
constant had no representable payload shape.  That negative was **retired** when the
container branch landed (``AuthoringGraph.cs`` ``case "dict"`` + ``AuthorWriteDict``;
``author.validate_dict_payload``).  Two tests below were INVERTED to their positive
form: the same instrument now asserts the tag EXISTS and the malformed shapes are
still refused BY NAME.  The remaining assertions (``slot_for(27) is None``, ``plan``
and ``builder`` carry no container slot/tag, a list-of-dicts is refused) are UNCHANGED
and still true -- a dict is a container written per entry, exactly like ``list``,
which is likewise not a ``--slot``.

Why this exists (historical)
---------------
The wave brief says: keep the *narrow, true* negative.  Dictionaries are NOT an
absent family -- constructors exist (``1088 建立字典``, ``1788 拼装字典``), accessors
exist (``1158 以键查询字典值``), and their dict *pins* are generic (``serverParamType 0``).
What is missing is a way to write a dict **constant** into a concrete type-27 pin.

This test pins the payload-shape half of that claim (the offline half, independent of
the bridge): the plan / serialisation value format has **no tag** for a dict, and every
layer that validates a tagged value REFUSES ``dict`` **by name** (fail-closed), rather
than silently ignoring it.  So the gap is not "a profile entry we forgot to fill" -- it
is an absent value kind, mirrored deliberately at each layer.

The **positive control** is the ``list`` container: the shape validators DO carry a
container branch (``{"list":[{"int":1}]}`` is accepted), so the refusal of ``dict`` is
dict-specific, not a blanket refusal of containers.  Without this control a "0" would be
meaningless.  A *list of dicts* is also refused, which is where the dict element would
have to ride if a container path existed at all.

If a future change ever adds a real dict setter (``AuthorWriteScalar`` needs a dict
branch), these assertions are the ones to revisit -- and only then, together with the
missing setter, never by weakening this test alone.
"""

import importlib.util
import unittest
from pathlib import Path

from tools.gameplan import paramtypes, plan
from tools.gameplan.builder import _tagged

# <root>/tools/gameplan/tests/<this file>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_CS = _REPO_ROOT / "tools" / "editor-bridge" / "Adapter" / "AuthoringGraph.cs"
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"


def _load_author():
    """Import ``tools/authoring/author.py`` by path (it has an ``__main__`` guard)."""
    spec = importlib.util.spec_from_file_location("author_value_shape", _AUTHOR_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSlotMappingAbsent(unittest.TestCase):
    def test_slot_for_dict_is_none_with_positive_control(self):
        # The type-27 dict has no --slot.
        self.assertIsNone(paramtypes.slot_for(27))
        # Positive control on the SAME instrument: the int type-3 DOES have a slot,
        # so a None here is a real "no mapping", not a broken lookup.
        self.assertEqual(paramtypes.slot_for(3), "int")

    def test_plan_slots_exclude_containers(self):
        # Neither dict nor list is a legal const slot (list is not either -- the plan
        # slot set is scalars only).
        self.assertNotIn("dict", plan._SLOTS)
        self.assertNotIn("list", plan._SLOTS)
        # Positive control: the scalar slots are present on the same set.
        for slot in ("int", "uint", "enum", "float", "bool", "string"):
            with self.subTest(slot=slot):
                self.assertIn(slot, plan._SLOTS)


class TestTaggedRefusesContainers(unittest.TestCase):
    def test_tagged_refuses_dict_and_list_with_positive_control(self):
        # `_tagged` is the plan -> `--value-json` encoder.  It has no container branch.
        with self.assertRaises(ValueError):
            _tagged("dict", {"k": {"int": 1}})
        with self.assertRaises(ValueError):
            _tagged("list", [1])
        # Positive control: a scalar slot still encodes on the same call.
        self.assertEqual(_tagged("int", 3), '{"int": 3}')


class TestAuthorShapeValidator(unittest.TestCase):
    """Layer 4: ``author.validate_scalar_payload`` (runs before journal/lease/dispatch)."""

    @classmethod
    def setUpClass(cls):
        cls.author = _load_author()

    def test_dict_tag_is_accepted_and_malformed_dicts_refused_by_name(self):
        # FLIPPED 2026-10-12 (the capability landed).  The dict payload NAME is accepted --
        # exactly as the `list` name is -- and every malformed shape is still refused BY NAME.
        self.author.validate_scalar_payload(
            {"dict": [{"key": {"string": "hp"}, "value": {"int": 3}}]}
        )
        # An empty dict is accepted and writes zero entries -- parity with {"list": []}.
        self.author.validate_scalar_payload({"dict": []})
        # A JSON object (not the pair array) is the shape error the tag used to raise.
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload({"dict": {"k": {"int": 1}}})
        self.assertIn("AUTHOR_VALUE_DICT_SHAPE_INVALID", str(ctx.exception))
        # A nested container is not a legal leaf.
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload({"dict": [{"key": {"list": [1]}, "value": {"int": 3}}]})
        self.assertIn("AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED", str(ctx.exception))
        # A duplicate key is refused, not silently collapsed (the reason for array-of-pairs).
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload(
                {"dict": [{"key": {"string": "hp"}, "value": {"int": 1}},
                          {"key": {"string": "hp"}, "value": {"int": 2}}]}
            )
        self.assertIn("AUTHOR_VALUE_DICT_DUPLICATE_KEY", str(ctx.exception))

    def test_list_container_is_accepted_the_positive_control(self):
        # A list of scalars IS representable in the payload shape -- proving the
        # validator is not simply refusing every container.  This is the control that
        # makes the dict refusal meaningful.
        self.author.validate_scalar_payload({"list": [{"int": 1}, {"string": "x"}]})

    def test_list_of_dicts_is_refused(self):
        # A dict element cannot ride inside the one container branch that exists.
        with self.assertRaises(ValueError) as ctx:
            self.author.validate_scalar_payload({"list": [{"dict": {"int": 1}}]})
        self.assertIn("AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED", str(ctx.exception))


class TestAdapterShapeAbsent(unittest.TestCase):
    """Static read of the adapter's value schema (never executed, never dispatched)."""

    def setUp(self):
        self.assertTrue(_ADAPTER_CS.is_file(), f"adapter source missing: {_ADAPTER_CS}")
        self.src = _ADAPTER_CS.read_text(encoding="utf-8")

    def test_dict_tag_now_exists_in_the_value_schema(self):
        # FLIPPED 2026-10-12 (the capability landed).  Same instrument, same file, same run:
        # known-present literals are the control, and the dict tag is now one of them.
        self.assertIn("AUTHOR_VALUE_TYPE_UNSUPPORTED", self.src)  # positive control
        self.assertIn("AUTHOR_VALUE_LIST_INVALID", self.src)      # positive control
        # The positive: the dict tag and its writer exist in the value path.
        for needle in ("AUTHOR_VALUE_DICT", "AuthorWriteDict", "AUTHOR_VALUE_NOT_A_DICT"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.src)
        # UNCHANGED negative: there is still no `map` tag, and `schema`/`plan` key spelling
        # is not how the branch is named -- the ONE container the branch adds is `dict`.
        self.assertNotIn("AUTHOR_VALUE_MAP", self.src)

    def test_build_plan_value_path_keeps_the_scalar_dispatch(self):
        # The plan path calls `AuthorWriteScalar` directly for a scalar and now branches to
        # `AuthorWriteDict` for `{"dict": …}` (2026-10-12).  The scalar dispatch must stay --
        # the dict branch must not have swallowed it.
        self.assertIn("AuthorWriteScalar(scalar,val,slot);", self.src)   # plan path (scalar)
        self.assertIn("AuthorWritePinValue(", self.src)                  # set-value path
        self.assertIn('if(name=="list")', self.src)                      # the list branch
        self.assertIn('else if(payloadName=="dict")', self.src)          # the dict branch


if __name__ == "__main__":
    unittest.main()
