"""Offline tests for tools/editor-catalog/search-corpora.py.

Every fixture is a handful of SYNTHETIC `.cs` files under a TemporaryDirectory,
laid out to mimic the real `.runtime/editor-catalog/resolved*` siblings.  No
game, no editor, no real corpus, no network is touched.

The load-bearing test is SearchBothTests.test_pattern_only_in_second_corpus:
a symbol that exists in the SIBLING corpus only must still be found, because
the tool searches every discovered corpus rather than a caller-named one.

Run:
    PYTHONIOENCODING=utf-8 python -m unittest discover -s tools/editor-catalog/tests -p "test_search_corpora.py"
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


sc = module("search-corpora")


def write_corpus(root, name, files, sidecar=None):
    d = Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    for fname, body in files.items():
        (d / fname).write_text(body, encoding="utf-8")
    if sidecar is not None:
        (d / ".source.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return d


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sc.main(argv)
    return code, out.getvalue(), err.getvalue()


class DiscoveryTests(unittest.TestCase):
    def test_finds_only_resolved_prefix_with_cs(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_corpus(tmp, "resolved", {"A.cs": "class A {}"})
            write_corpus(tmp, "resolved-abc123", {"B.cs": "class B {}"})
            write_corpus(tmp, "annotated", {"C.cs": "class C {}"})   # wrong prefix
            write_corpus(tmp, "resolved-empty", {})                  # no .cs
            names = [c["name"] for c in sc.discover_corpora(tmp)]
            self.assertEqual(names, ["resolved", "resolved-abc123"])
            counts = {c["name"]: c["csCount"] for c in sc.discover_corpora(tmp)}
            self.assertEqual(counts, {"resolved": 1, "resolved-abc123": 1})

    def test_missing_catalog_dir_is_empty_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sc.discover_corpora(Path(tmp) / "nope"), [])


class IdentityTests(unittest.TestCase):
    def test_sidecar_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_corpus(tmp, "resolved-x", {"A.cs": "x"},
                             sidecar={"sourceSha256": "deadbeef", "profile": "editor-7.1",
                                      "filesScanned": 12955})
            ident = sc.read_build_identity(d)
            self.assertEqual(ident["sourceSha256"], "deadbeef")
            self.assertEqual(ident["profile"], "editor-7.1")
            self.assertEqual(ident["filesScanned"], 12955)

    def test_no_sidecar_is_null_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_corpus(tmp, "resolved", {"A.cs": "x"})
            ident = sc.read_build_identity(d)
            self.assertIsNone(ident["sourceSha256"])
            self.assertIsNone(ident["profile"])


class PatternTests(unittest.TestCase):
    def test_fixed_escapes_regex_metachars(self):
        self.assertIsNotNone(sc.compile_pattern("a.b", True).search("a.b"))
        self.assertIsNone(sc.compile_pattern("a.b", True).search("axb"))
        self.assertIsNotNone(sc.compile_pattern("a.b", False).search("axb"))


class SearchBothTests(unittest.TestCase):
    def _two_corpora(self, tmp):
        # 7.0-style corpus: NO sidecar. 7.1-style corpus: sidecar present.
        write_corpus(tmp, "resolved", {"Old.cs": "DeleteComponentForEditObj();\nnoop();\n"})
        write_corpus(tmp, "resolved-565dda11",
                     {"New.cs": "// nothing here\nSiblingOnlySymbol();\n"},
                     sidecar={"sourceSha256": "565dda11" + "0" * 56, "profile": "editor-7.1"})

    def test_pattern_only_in_second_corpus_is_found(self):
        # THE regression: the symbol exists ONLY in the sibling.  A single-corpus
        # search of `resolved/` would report a false negative.
        with tempfile.TemporaryDirectory() as tmp:
            self._two_corpora(tmp)
            corpora = sc.discover_corpora(tmp)
            regex = sc.compile_pattern("SiblingOnlySymbol", fixed=True)
            results = sc.search_corpora(corpora, regex)
            by = {r["name"]: r for r in results}
            self.assertEqual(by["resolved-565dda11"]["matchCount"], 1)
            self.assertEqual(by["resolved"]["matchCount"], 0)

    def test_all_discovered_corpora_are_searched(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._two_corpora(tmp)
            results = sc.search_corpora(sc.discover_corpora(tmp),
                                        sc.compile_pattern("Symbol|Component", False))
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r["filesMatched"] >= 0 for r in results))


class VerdictTests(unittest.TestCase):
    def test_require_both_fails_on_single_corpus(self):
        code, msg = sc.verdict([{"name": "resolved"}], require_both=True)
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", msg)

    def test_require_both_passes_on_two(self):
        code, msg = sc.verdict([{"name": "a"}, {"name": "b"}], require_both=True)
        self.assertEqual(code, 0)
        self.assertIsNone(msg)

    def test_disabled_requirement_allows_one(self):
        code, _ = sc.verdict([{"name": "a"}], require_both=False)
        self.assertEqual(code, 0)


class MainTests(unittest.TestCase):
    def test_main_searches_both_and_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_corpus(tmp, "resolved", {"A.cs": "TargetSymbol();\n"})
            write_corpus(tmp, "resolved-565dda11", {"B.cs": "TargetSymbol();\n"})
            code, out, _ = run_main(["--pattern", "TargetSymbol", "--fixed",
                                     "--catalog-dir", tmp, "--json"])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(len(data["corpora"]), 2)
            self.assertEqual(sum(c["matchCount"] for c in data["corpora"]), 2)

    def test_main_require_both_fails_on_one_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_corpus(tmp, "resolved", {"A.cs": "x\n"})
            code, out, _ = run_main(["--pattern", "x", "--catalog-dir", tmp, "--json"])
            self.assertEqual(code, 2)
            self.assertIn("REFUSED", json.loads(out)["message"])

    def test_main_bad_pattern_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main(["--pattern", "(", "--catalog-dir", tmp])
            self.assertEqual(code, 1)
            self.assertIn("bad pattern", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
