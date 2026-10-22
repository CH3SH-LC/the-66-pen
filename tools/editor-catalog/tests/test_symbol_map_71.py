"""Offline tests for tools/editor-catalog/symbol-map-71.py.

All mapping behaviour is exercised on SYNTHETIC in-memory maps -- no game, no
editor, no binary, no network. A final group checks the script against the real
curated 7.1 map on disk (read-only).

Run:
    PYTHONIOENCODING=utf-8 python -m unittest tools.editor-catalog.tests.test_symbol_map_71
or, from the repo root:
    PYTHONIOENCODING=utf-8 python -m unittest discover -s tools/editor-catalog/tests -p "test_symbol_map_71.py"
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


sm = module("symbol-map-71")

# Synthetic map.  Keys mirror the two shapes the real map actually contains:
# type full names ("Ns.Type") and bare member leaf names ("doThing").
SYN = {
    "Alpha.Beta": "Gamma.Delta",       # namespace-qualified type
    "doThing": "doThingX",             # bare member leaf (method/field)
    "Owner.method": "OwnerX.methodX",  # hypothetical qualified member key
    "Same.Name": "Same.Name",          # identity mapping
    "Zeta": "Eta",                     # bare type name (no namespace)
}


class ExactMatchTests(unittest.TestCase):
    def setUp(self):
        self.m = sm.SymbolMap71(SYN)

    def test_exact_type_key_maps(self):
        r = self.m.lookup("Alpha.Beta")
        self.assertEqual(r["status"], sm.STATUS_MAPPED)
        self.assertEqual(r["new"], "Gamma.Delta")
        self.assertEqual(r["nearMisses"], [])

    def test_exact_bare_member_key_maps(self):
        self.assertEqual(self.m.lookup("doThing")["new"], "doThingX")

    def test_exact_bare_type_key_maps(self):
        self.assertEqual(self.m.lookup("Zeta")["new"], "Eta")

    def test_identity_mapping_flagged(self):
        r = self.m.lookup("Same.Name")
        self.assertEqual(r["status"], sm.STATUS_MAPPED)
        self.assertTrue(r["identity"])
        self.assertEqual(r["new"], "Same.Name")

    def test_unknown_reports_unknown_with_no_value(self):
        r = self.m.lookup("No.Such.Symbol")
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])
        self.assertFalse(r["identity"])


class NoPartialMatchTests(unittest.TestCase):
    """A prefix, suffix or substring of a key is NEVER returned as an answer."""

    def setUp(self):
        self.m = sm.SymbolMap71(SYN)

    def test_suffix_of_key_is_refused(self):
        r = self.m.lookup("Beta")           # suffix of "Alpha.Beta"
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])
        self.assertIn("Alpha.Beta", r["nearMisses"])

    def test_prefix_of_key_is_refused(self):
        r = self.m.lookup("Alpha")          # prefix of "Alpha.Beta"
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])
        self.assertIn("Alpha.Beta", r["nearMisses"])

    def test_longer_than_key_is_refused(self):
        r = self.m.lookup("Alpha.Beta.Extra")  # key is a prefix of the query
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])
        self.assertIn("Alpha.Beta", r["nearMisses"])

    def test_member_leaf_is_not_qualified_by_invention(self):
        # Map holds bare "doThing"; a qualified query must NOT be auto-qualified
        # to match it.  "Owner.doThing" is not a key, so it is unknown.
        r = self.m.lookup("Owner.doThing")
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])

    def test_different_owner_qualified_is_refused(self):
        # "Owner.method" is a key; "Other.method" must not borrow its value.
        r = self.m.lookup("Other.method")
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])

    def test_near_misses_are_never_the_answer(self):
        # Every substring-similar key returned by near_misses must itself be a
        # real key, and none of them may be produced as the value.
        r = self.m.lookup("method")
        self.assertIsNone(r["new"])
        for key in r["nearMisses"]:
            self.assertIn(key, self.m)
            self.assertNotEqual(key, r["new"])


class MemberLookupTests(unittest.TestCase):
    def setUp(self):
        self.m = sm.SymbolMap71(SYN)

    def test_qualified_key_hit_reports_form(self):
        r = self.m.attempt_member_lookup("Owner", "method")
        self.assertEqual(r["status"], sm.STATUS_MAPPED)
        self.assertEqual(r["new"], "OwnerX.methodX")
        self.assertEqual(r["matchedForm"], "Owner.method")

    def test_bare_leaf_hit_uses_bare_form(self):
        r = self.m.attempt_member_lookup("Ghost", "doThing")  # owner unknown
        self.assertEqual(r["status"], sm.STATUS_MAPPED)
        self.assertEqual(r["new"], "doThingX")
        self.assertEqual(r["matchedForm"], "doThing")
        self.assertEqual(r["owner"], "Ghost")

    def test_absent_member_is_unknown(self):
        r = self.m.attempt_member_lookup("Owner", "nope")
        self.assertEqual(r["status"], sm.STATUS_UNKNOWN)
        self.assertIsNone(r["new"])
        self.assertIsNone(r["matchedForm"])

    def test_owner_must_be_string(self):
        with self.assertRaises(sm.SymbolMapError):
            self.m.attempt_member_lookup(None, "doThing")


class InvariantTests(unittest.TestCase):
    def test_no_key_ever_resolves_to_a_different_value(self):
        m = sm.SymbolMap71(SYN)
        for key, value in SYN.items():
            r = m.lookup(key)
            self.assertEqual(r["status"], sm.STATUS_MAPPED, key)
            self.assertEqual(r["new"], value, key)

    def test_non_keys_are_unknown(self):
        m = sm.SymbolMap71(SYN)
        for query in ["", " ", "Gamma.Delta", "x", "Alpha.Beta.", ".Alpha.Beta", "ETA"]:
            r = m.lookup(query)
            self.assertEqual(r["status"], sm.STATUS_UNKNOWN, query)
            self.assertIsNone(r["new"], query)

    def test_lookup_many_preserves_order(self):
        m = sm.SymbolMap71(SYN)
        rs = m.lookup_many(["doThing", "missing", "Zeta"])
        self.assertEqual([x["old"] for x in rs], ["doThing", "missing", "Zeta"])
        self.assertEqual([x["status"] for x in rs],
                         [sm.STATUS_MAPPED, sm.STATUS_UNKNOWN, sm.STATUS_MAPPED])

    def test_non_string_query_raises(self):
        m = sm.SymbolMap71(SYN)
        with self.assertRaises(sm.SymbolMapError):
            m.lookup(None)
        with self.assertRaises(sm.SymbolMapError):
            m.lookup(123)

    def test_near_misses_empty_for_blank(self):
        m = sm.SymbolMap71(SYN)
        self.assertEqual(m.near_misses(""), [])
        self.assertEqual(m.near_misses(None), [])


class ConstructionTests(unittest.TestCase):
    def test_rejects_non_mapping(self):
        with self.assertRaises(sm.SymbolMapError):
            sm.SymbolMap71(["Alpha.Beta"])
        with self.assertRaises(sm.SymbolMapError):
            sm.SymbolMap71(None)

    def test_rejects_non_string_entries(self):
        with self.assertRaises(sm.SymbolMapError):
            sm.SymbolMap71({"a": 1})
        with self.assertRaises(sm.SymbolMapError):
            sm.SymbolMap71({2: "b"})

    def test_defensive_copy(self):
        src = {"A": "B"}
        m = sm.SymbolMap71(src)
        src["A"] = "C"
        self.assertEqual(m.lookup("A")["new"], "B")

    def test_load_roundtrip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.json"
            path.write_text(json.dumps(SYN), encoding="utf-8")
            m = sm.SymbolMap71.load(path)
            self.assertEqual(len(m), len(SYN))
            self.assertEqual(m.lookup("doThing")["new"], "doThingX")
        with self.assertRaises(sm.SymbolMapError):
            sm.SymbolMap71.load(Path(tmp) / "does-not-exist.json")

    def test_load_rejects_non_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(sm.SymbolMapError):
                sm.SymbolMap71.load(path)


class RealMapTests(unittest.TestCase):
    """Read-only checks against the curated map on disk (regression guard)."""

    def setUp(self):
        self.m = sm.SymbolMap71.load()
        self.raw = json.loads(sm.DEFAULT_MAP.read_text(encoding="utf-8"))

    def test_map_is_flat_str_to_str(self):
        self.assertIsInstance(self.raw, dict)
        self.assertGreater(len(self.raw), 200)
        for k, v in self.raw.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, str)

    def test_script_agrees_with_raw_json_on_every_key(self):
        for k, v in self.raw.items():
            self.assertEqual(self.m.lookup(k)["new"], v, k)

    def test_project_symbols_are_unknown_on_the_curated_map(self):
        # The four authoring symbols the project cares about (component panel /
        # row VM, component model type, the two list VMs) plus the delete
        # handler.  None is a reflective Adapter binding, so the curated map
        # answers "unknown" -- and the tool must not invent a partial match.
        names = [
            "pmZ1POuub8FEemimgKKq.yn34VuuuO5tEgsICYDBW",  # component panel/row VM
            "taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW",  # component model type
            "LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN",  # list VM #1
            "yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ",  # list VM #2
            "s9puu4bEcx2",                                # delete handler
        ]
        for name in names:
            r = self.m.lookup(name)
            self.assertEqual(r["status"], sm.STATUS_UNKNOWN, name)
            self.assertIsNone(r["new"], name)


if __name__ == "__main__":
    unittest.main()
