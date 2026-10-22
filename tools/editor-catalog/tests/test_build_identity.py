# -*- coding: utf-8 -*-
"""Offline tests for tools/editor-catalog/build-identity.py.

Every classification path is exercised on SYNTHETIC fixtures -- a small census
JSON and a throwaway corpus directory built inside a temp dir.  No game, no
editor, no DLL, no network.  A final group runs the real on-disk census + corpus
read-only, and is skipped if either is absent.

Run:
    PYTHONIOENCODING=utf-8 python -m unittest discover -s tools/editor-catalog/tests -p "test_build_identity.py"
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOOLS = PROJECT_ROOT / "tools" / "editor-catalog"
sys.path.insert(0, str(TOOLS))


def _load_module(name):
    path = TOOLS / (name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bi = _load_module("build-identity")

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_census(namespaces, sha=SHA_A):
    """A minimal census whose `types` carry the given namespaces."""
    types = []
    for i, ns in enumerate(namespaces):
        types.append({"fullName": "%s.T%d" % (ns, i), "name": "T%d" % i,
                      "namespace": ns, "isNested": False})
    return {
        "schema": "editor-method-census/1",
        "sourceSha256": sha,
        "typeCount": len(types),
        "types": types,
    }


def make_corpus(root, namespaces, source_sha=None, bare_classes=()):
    """Write `Ns.Class.cs` files (plus optional bare `Class.cs`) and .source.json."""
    for i, ns in enumerate(namespaces):
        name = ("%s.C%d.cs" % (ns, i)) if ns else ("C%d.cs" % i)
        (root / name).write_text("namespace %s;\n" % (ns or "_"), encoding="utf-8")
    for cls in bare_classes:
        (root / ("%s.cs" % cls)).write_text("// bare\n", encoding="utf-8")
    if source_sha is not None:
        (root / ".source.json").write_text(
            json.dumps({"sourceSha256": source_sha}), encoding="utf-8")


class NamespaceExtractionTests(unittest.TestCase):
    def test_qualified_name_yields_namespace(self):
        with tempfile.TemporaryDirectory() as d:
            make_corpus(Path(d), ["Alpha.Beta"])
            self.assertEqual(bi.corpus_namespaces(d), {"Alpha.Beta"})

    def test_bare_class_file_yields_empty_namespace(self):
        with tempfile.TemporaryDirectory() as d:
            make_corpus(Path(d), [], bare_classes=["Solo"])
            self.assertEqual(bi.corpus_namespaces(d), {""})

    def test_nested_and_arity_underscore_only_touch_type_segment(self):
        # `Ns.Name_3.cs` (arity/nesting mangled to _) still yields namespace `Ns`.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Ns.Name_3.cs").write_text("// x\n", encoding="utf-8")
            self.assertEqual(bi.corpus_namespaces(d), {"Ns"})

    def test_missing_source_json_yields_none(self):
        with tempfile.TemporaryDirectory() as d:
            make_corpus(Path(d), ["A"])
            self.assertIsNone(bi.corpus_source_sha256(d))

    def test_source_json_sha_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            make_corpus(Path(d), ["A"], source_sha=SHA_B)
            self.assertEqual(bi.corpus_source_sha256(d), SHA_B)


class VerdictTests(unittest.TestCase):
    # Small synthetic sets: pass min_shared=0 so coverage governs the verdict;
    # the min_shared floor has its own dedicated test below.
    def test_full_namespace_alignment_is_same_build(self):
        r = bi.classify({"A", "B", "C"}, {"A", "B", "C"}, SHA_A, None, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_SAME)
        self.assertEqual(r["reason"], bi.REASON_NAMESPACE_COVERAGE)
        self.assertEqual(r["namespaceIntersection"], 3)
        self.assertEqual(r["coverage"], 1.0)

    def test_disjoint_namespaces_are_different_build(self):
        r = bi.classify({"A", "B", "C"}, {"X", "Y", "Z"}, SHA_A, None, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(r["reason"], bi.REASON_LOW_OVERLAP)
        self.assertEqual(r["namespaceIntersection"], 0)

    def test_sha_match_forces_same_build_even_on_low_overlap(self):
        r = bi.classify({"A"}, {"Z"}, SHA_A, SHA_A, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_SAME)
        self.assertEqual(r["reason"], bi.REASON_SHA_MATCH)

    def test_sha_mismatch_reports_named_reason(self):
        r = bi.classify({"A", "B", "C"}, {"X"}, SHA_A, SHA_B, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(r["reason"], bi.REASON_SHA_MISMATCH)

    def test_sha_mismatch_beats_full_namespace_coverage(self):
        # Perfect namespace alignment is NOT enough when the recorded bytes
        # differ -- a patched DLL must never be reported as the same build.
        r = bi.classify({"A", "B", "C"}, {"A", "B", "C"}, SHA_A, SHA_B, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(r["reason"], bi.REASON_SHA_MISMATCH)

    def test_empty_corpus_fails_closed(self):
        r = bi.classify({"A", "B", "C"}, set(), SHA_A, None, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(r["reason"], bi.REASON_NO_CORPUS_NAMESPACES)
        self.assertEqual(r["coverage"], 0.0)

    def test_empty_census_fails_closed(self):
        r = bi.classify(set(), {"A"}, None, None, min_shared=0)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(r["reason"], bi.REASON_NO_CENSUS_NAMESPACES)

    def test_partial_overlap_above_threshold_is_same(self):
        census = {"N%d" % i for i in range(100)}
        corpus = {"N%d" % i for i in range(99)} | {"NewOne"}   # 99/100 on corpus side
        r = bi.classify(census, corpus, None, None)            # min side = 100 -> .99
        self.assertEqual(r["verdict"], bi.VERDICT_SAME)
        self.assertAlmostEqual(r["coverage"], 0.99)

    def test_partial_overlap_below_threshold_is_different(self):
        census = {"N%d" % i for i in range(100)}
        corpus = {"N%d" % i for i in range(50)} | {"X%d" % i for i in range(50)}
        r = bi.classify(census, corpus, None, None)            # min side = 100 -> .50
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)
        self.assertAlmostEqual(r["coverage"], 0.5)

    def test_tiny_perfect_overlap_below_min_shared_is_different(self):
        # coverage is 1.0 but only 3 shared -> under the default --min-shared
        # floor of 20, the verdict must fail closed.
        r = bi.classify({"A", "B", "C"}, {"A", "B", "C"}, None, None)
        self.assertEqual(r["verdict"], bi.VERDICT_DIFFERENT)

    def test_threshold_is_configurable(self):
        census = {"N%d" % i for i in range(100)}
        corpus = {"N%d" % i for i in range(60)} | {"X%d" % i for i in range(40)}
        strict = bi.classify(census, corpus, None, None, threshold=0.95)
        loose = bi.classify(census, corpus, None, None, threshold=0.50)
        self.assertEqual(strict["verdict"], bi.VERDICT_DIFFERENT)
        self.assertEqual(loose["verdict"], bi.VERDICT_SAME)


class AnalyzeAndCliTests(unittest.TestCase):
    def _fixture(self, tmp, namespaces, sha=SHA_A, source_sha=SHA_A):
        census_path = Path(tmp) / "census.json"
        census_path.write_text(json.dumps(make_census(namespaces, sha)),
                               encoding="utf-8")
        corpus_dir = Path(tmp) / "corpus"
        corpus_dir.mkdir()
        make_corpus(corpus_dir, namespaces, source_sha=source_sha)
        return census_path, corpus_dir

    def test_analyze_reports_typecount_and_same(self):
        with tempfile.TemporaryDirectory() as d:
            census_path, corpus_dir = self._fixture(d, ["Alpha", "Beta"])
            r = bi.analyze(census_path, corpus_dir)
            self.assertEqual(r["verdict"], bi.VERDICT_SAME)
            self.assertEqual(r["typeCount"], 2)
            self.assertEqual(r["censusNamespaceCount"], 2)

    def test_cli_exit_zero_on_same(self):
        with tempfile.TemporaryDirectory() as d:
            census_path, corpus_dir = self._fixture(d, ["Alpha", "Beta"])
            proc = subprocess.run(
                [sys.executable, str(TOOLS / "build-identity.py"),
                 "--census", str(census_path), "--corpus", str(corpus_dir)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("SAME-BUILD", proc.stdout)

    def test_cli_exit_two_and_emits_rule_on_different(self):
        with tempfile.TemporaryDirectory() as d:
            census_path = Path(d) / "census.json"
            census_path.write_text(json.dumps(make_census(["Alpha"], SHA_A)),
                                   encoding="utf-8")
            corpus_dir = Path(d) / "corpus"
            corpus_dir.mkdir()
            make_corpus(corpus_dir, ["Zulu"], source_sha=SHA_B)
            proc = subprocess.run(
                [sys.executable, str(TOOLS / "build-identity.py"),
                 "--census", str(census_path), "--corpus", str(corpus_dir)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("DIFFERENT-BUILD", proc.stdout)
            self.assertIn("RULE:", proc.stdout)


class RealCorpusTests(unittest.TestCase):
    """Read-only check against the artefacts on disk (skipped if absent)."""

    CENSUS = PROJECT_ROOT / ".runtime" / "scratch" / "editor-method-census.json"
    CORPUS = (PROJECT_ROOT / ".runtime" / "verification" / "update-repair-20260925"
              / "strings" / "annotated-7.1")

    def test_real_artifacts_are_same_build(self):
        if not self.CENSUS.is_file() or not self.CORPUS.is_dir():
            self.skipTest("real census/corpus not present on this checkout")
        r = bi.analyze(self.CENSUS, self.CORPUS)
        self.assertEqual(r["verdict"], bi.VERDICT_SAME)
        # The two artefact families agree byte-for-byte and by namespace coverage.
        self.assertTrue(r["shaMatch"])
        self.assertEqual(r["censusNamespaceCount"], r["corpusNamespaceCount"])
        self.assertEqual(r["namespaceIntersection"], r["corpusNamespaceCount"])
        self.assertEqual(r["typeCount"], 15653)


if __name__ == "__main__":
    unittest.main()
