"""Mutation controls for tools/game-executor/verify_run_provenance.py -- the F-010 layer.

WHY THIS FILE EXISTS IN THE TREE
================================
The layer's own module docstring says, verbatim:

    "There is no relaxation switch: every obligation in ``provenance-contract-v1.md``
     is always enforced.  Mutation controls live in the test suite, not in this
     interface."

Until this file existed that sentence was FALSE IN THE REPOSITORY.  The suites that
were actually written for this layer lived under

    .runtime/cordis-plan-work/R19-A1-F010PROD-20261002/tests/
    .runtime/cordis-plan-work/R24-A23-VERIFIERFIX-20261002/candidate/tests/

and ``/.runtime/`` is in ``.gitignore``.  So a fresh clone carried no control over the
top-priority C1 artifact at all, and a ``.runtime`` clean would delete the last one.
This is the same defect family as the G02 gate, which was vendored into
``tools/game-executor/vendor/`` for exactly this reason; it is fixed here the same way.

Symmetry note (found while triaging, not fixed here): the F-011 ownership-legs guard
suite inherits the same problem -- ``rg --no-ignore READBACK_HASH_MISMATCH .`` hits only
the module, never a test.

WHAT IT PINS (the SHIPPED behaviour, not an aspirational one)
============================================================
Three guards in the shipped layer exist to convert a CRASH into a structured rejection
or to stop a repository-wide walk.  They are the difference between "the verifier
refused" and "the verifier died", and that difference is load-bearing for C1: a layer
that tracebacks emits no verdict body, so nothing downstream can tell refusal from
failure.

  A26-C1  ``_excluded_from_corpus`` must return empty for a non-object anchor.  The
          call runs BEFORE the ``PROVENANCE_NOT_OBJECT`` type check, so without this
          guard the AttributeError escapes ``run()`` and that branch is dead.
  A26-S1  the same shape for ``evidence-index.json``: a run-supplied ``[]``/``"x"``/
          ``null`` index must not crash ``body_path()``.
  A26-C2  a blank locator must not be resolved.  ``Path("") == Path(".")``, so
          ``repo_root / ""`` is ``repo_root`` and the rglob walks the whole repository
          (measured: 493,426 files, ~13 min).  Blank is skipped; ``load_sources``
          already rejects it, so nothing that was refused becomes accepted.

Two honest divergences from the R24 candidate, MEASURED 2026-10-05 by running that
candidate suite against this shipped file -- 2 of its 11 tests are red here:

  D1  R24 moved the type check *above* the corpus build; the shipped layer instead
      guards the crash site and keeps the order.  Both refuse a non-object anchor with
      ``PROVENANCE_NOT_OBJECT`` and exit 1; the shipped order additionally scans the
      corpus first.  That is a cost difference, not a soundness difference.  The tests
      below pin what the shipped code guarantees (structured rejection, never a
      traceback) and do NOT assert the ordering, because the ordering is not the
      shipped contract.
  D2  R24 also expected a ``locator: "."`` anchor not to walk the repository.  The
      ORIGINAL shipped code deliberately left ``.``/``..`` alone ("the separate,
      user-owned S2 decision"), and that expectation was recorded as an expectedFailure.
      R03 then DISCHARGED the decision: a source locator must now resolve inside a
      producer directory DERIVED from the producer's own configuration, so ``.``/``..``
      are refused by name and no longer walk the repository.  The expectedFailure is
      therefore replaced by a live assertion, and the original verdict text is preserved
      verbatim in its docstring.

Run:
    python -m unittest discover -s tools/game-executor/tests -p "test_verify_run_provenance.py" -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYER = HERE.parent / "verify_run_provenance.py"
sys.path.insert(0, str(HERE.parent))
import verify_run_provenance as vrp

RUN_ID = "c" * 32
ANCHOR_NAME = "provenance.input.json"


def _load_layer_from_source(source: str) -> dict:
    """Load a mutated copy of the layer.  The only mutation seam this file needs."""
    namespace = {"__name__": "vrp_mutant", "__file__": str(LAYER)}
    exec(compile(source, str(LAYER), "exec"), namespace)
    return namespace


def _synthetic_repo(tmp: Path) -> Path:
    """A tiny stand-in for the repository root: one producer dir, one noise file."""
    repo = tmp / "repo"
    (repo / "producer").mkdir(parents=True)
    (repo / "producer" / "receipt.json").write_text("{}\n", encoding="utf-8")
    (repo / "noise").mkdir()
    (repo / "noise" / "junk.txt").write_text("x\n", encoding="utf-8")
    return repo


def _write_anchor(run_root: Path, payload: str) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / ANCHOR_NAME).write_text(payload + "\n", encoding="utf-8", newline="\n")


def _layer(run_root: Path, repo: Path, allowed_source_roots=None):
    """A layer whose corpus scan is empty and whose base verdict is skipped.

    ``corpus_roots=[]`` keeps every test hermetic -- no test here may walk the real
    producer spaces.  ``base_skipped`` removes the frozen gate from the picture, so a
    red test means the LAYER misbehaved and never the base verifier.  The synthetic
    repo's ``producer`` directory is the default allowed SOURCE scope, so a locator of
    ``producer`` stays a legitimate witness (R03); pass ``allowed_source_roots`` to
    override it, or construct ``vrp.ProvenanceLayer`` directly to exercise the DERIVED
    default.
    """
    return vrp.ProvenanceLayer(
        run_root, {}, 1, repo, corpus_roots=[], base_skipped=True,
        allowed_source_roots=(allowed_source_roots if allowed_source_roots is not None
                              else [repo / "producer"]))


def _codes(defects):
    return {d["code"] for d in defects}


class A26C1NonObjectAnchorTests(unittest.TestCase):
    """A non-object anchor must be refused, never survived by luck."""

    def test_exclusion_scan_is_empty_for_a_non_object_anchor(self):
        """A26-C1: the guard that makes every other test in this class reachable."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, '"not-an-object"')

            self.assertEqual(_layer(run_root, repo)._excluded_from_corpus(), frozenset())

    def test_run_emits_a_structured_rejection_for_every_non_object_shape(self):
        """string / null / array / number: all four refused, none of them crashes."""
        for payload in ('"s"', "null", "[1,2]", "17"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                repo = _synthetic_repo(Path(tmp))
                run_root = Path(tmp) / RUN_ID
                _write_anchor(run_root, payload)

                layer = _layer(run_root, repo)
                layer.load_frozen = lambda: None          # frozen pin is not what is under test
                verdict = layer.run()

                self.assertIn("PROVENANCE_NOT_OBJECT", _codes(verdict["provenanceDefects"]))
                self.assertFalse(verdict["ok"])
                self.assertFalse(verdict["authenticityAccepted"])

    def test_cli_refuses_a_non_object_anchor_with_a_verdict_body_and_no_traceback(self):
        """The end-to-end shape C1 depends on: exit 1, parseable verdict, no traceback."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / RUN_ID
            _write_anchor(run_root, "null")
            empty_corpus = tmp_path / "corpus"
            empty_corpus.mkdir()

            proc = subprocess.run(
                [sys.executable, "-B", str(LAYER), str(run_root),
                 "--corpus-roots", str(empty_corpus), "--quiet"],
                capture_output=True, text=True)

            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            verdict = json.loads(proc.stdout)
            self.assertIn("PROVENANCE_NOT_OBJECT", _codes(verdict["provenanceDefects"]))

    def test_a_non_object_evidence_index_does_not_crash(self):
        """A26-S1: evidence-index.json is run-supplied too."""
        for payload in ("[]", '"x"', "null"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                repo = _synthetic_repo(Path(tmp))
                run_root = Path(tmp) / RUN_ID
                _write_anchor(run_root, json.dumps({"sources": []}))
                (run_root / "evidence-index.json").write_text(payload + "\n", encoding="utf-8")

                layer = _layer(run_root, repo)
                layer.load_frozen = lambda: None
                verdict = layer.run()                      # must return, not raise

                self.assertIsInstance(verdict, dict)

    def test_a_missing_anchor_is_still_refused(self):
        """A26-C1 must not have replaced the absent-anchor branch with silence."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            run_root.mkdir(parents=True, exist_ok=True)

            layer = _layer(run_root, repo)
            layer.load_frozen = lambda: None
            verdict = layer.run()

            self.assertIn("PROVENANCE_ABSENT", _codes(verdict["provenanceDefects"]))


class A26C2DegenerateLocatorTests(unittest.TestCase):
    """A blank or absent locator must not become a repository-wide walk."""

    def test_blank_locators_do_not_resolve_to_the_repo_root(self):
        for locator in ("", "   ", "\t"):
            with self.subTest(locator=locator), tempfile.TemporaryDirectory() as tmp:
                repo = _synthetic_repo(Path(tmp))
                run_root = Path(tmp) / RUN_ID
                _write_anchor(run_root, json.dumps({"sources": [
                    {"sourceId": "s", "kind": "helper-receipt", "locator": locator}]}))

                self.assertEqual(_layer(run_root, repo)._excluded_from_corpus(), frozenset())

    def test_absent_locator_does_not_resolve_to_the_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt"}]}))

            self.assertEqual(_layer(run_root, repo)._excluded_from_corpus(), frozenset())

    def test_not_scanning_does_not_mean_not_rejecting(self):
        """The blank locator must still be refused downstream, or C1 would lose a refusal."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            source = {"sourceId": "s", "kind": "helper-receipt", "locator": ""}
            _write_anchor(run_root, json.dumps({"sources": [source]}))

            layer = _layer(run_root, repo)
            layer.load_sources({"sources": [source]})

            self.assertIn("PROVENANCE_SOURCE_LOCATOR_INVALID", _codes(layer.defects))

    def test_a_legitimate_relative_locator_is_still_excluded(self):
        """Guard rail: the fix must not stop a REAL locator from being excluded.

        If the anchor's own source directory stayed in the corpus, the anchor could
        corroborate itself and the layer's whole independence claim would collapse.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": "producer",
                 "directoryManifestSha256": "0" * 64}]}))

            excluded = _layer(run_root, repo)._excluded_from_corpus()

            self.assertIn((repo / "producer" / "receipt.json").resolve(), excluded)
            self.assertNotIn((repo / "noise" / "junk.txt").resolve(), excluded)

    def test_the_dot_locator_no_longer_walks_the_repo_root(self):
        """R03 DISCHARGED the old "separate, user-owned S2 decision".

        The verdict it replaced, preserved verbatim:

            "RECORDED DEVIATION, not a wish. ``locator: '.'`` is left intact by design
             ('the separate, user-owned S2 decision'). It therefore still resolves to the
             repository root and walks it. This is a cost, not a soundness hole -- the
             walk excludes the whole repo, so the corpus comes back empty and the run is
             refused with PROVENANCE_CORPUS_EMPTY."

        The decision is now made: a locator must resolve inside a producer directory
        DERIVED from the producer's own configuration, so ``.`` is refused by name and
        the repository is no longer walked.  The verdict outcome is unchanged -- the run
        is still refused -- but it is no longer refused for the wrong reason.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": "."}]}))

            layer = _layer(run_root, repo)
            self.assertEqual(layer._excluded_from_corpus(), frozenset())
            sources = layer.load_sources({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": "."}]})
            self.assertIn("PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE",
                          {d["code"] for d in layer.defects})
            self.assertEqual(sources["s"]["scalars"], set())


class A26C3NonIterableSourcesTests(unittest.TestCase):
    """A26-C3: a NON-LIST ``sources`` must be refused, not survived by a crash.

    Found 2026-10-05 by the W20 independent verifier and reproduced by the main line:
    ``{"sources": 5}`` made the layer exit 1 with a ``TypeError: 'int' object is not
    iterable`` traceback and NO verdict body.  ``doc`` is a valid object, so A26-C1 did
    not cover it, and ``or []`` does not rescue a truthy non-iterable.

    The first suite written for this layer (round 115) had this hole: it tested a
    non-object anchor and a non-object index, but not a non-list ``sources`` inside an
    otherwise valid one.  These cases exist because an independent reviewer found it.
    """

    NON_LISTS = ('{"sources": 5}', '{"sources": true}', '{"sources": "x"}', '{"sources": 0}')

    def test_non_list_sources_does_not_crash_the_exclusion_scan(self):
        for payload in self.NON_LISTS:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                repo = _synthetic_repo(Path(tmp))
                run_root = Path(tmp) / RUN_ID
                _write_anchor(run_root, payload)

                self.assertEqual(_layer(run_root, repo)._excluded_from_corpus(), frozenset())

    def test_run_refuses_a_non_list_sources_with_a_structured_defect(self):
        for payload in self.NON_LISTS:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                repo = _synthetic_repo(Path(tmp))
                run_root = Path(tmp) / RUN_ID
                _write_anchor(run_root, payload)

                layer = _layer(run_root, repo)
                layer.load_frozen = lambda: None
                verdict = layer.run()                       # must return, not raise

                self.assertFalse(verdict["ok"])
                self.assertIn("PROVENANCE_SOURCES_ABSENT", _codes(verdict["provenanceDefects"]))

    def test_cli_refuses_a_non_list_sources_without_a_traceback(self):
        """The shape that was broken: exit 1 + parseable verdict, never a traceback."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / RUN_ID
            _write_anchor(run_root, '{"sources": 5}')
            empty_corpus = tmp_path / "corpus"
            empty_corpus.mkdir()

            proc = subprocess.run(
                [sys.executable, "-B", str(LAYER), str(run_root),
                 "--corpus-roots", str(empty_corpus), "--quiet"],
                capture_output=True, text=True)

            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            verdict = json.loads(proc.stdout)
            self.assertIn("PROVENANCE_SOURCES_ABSENT", _codes(verdict["provenanceDefects"]))

    def test_a_legitimate_list_of_sources_is_still_scanned(self):
        """Guard rail: the fix must not stop a REAL sources list from being excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": "producer"}]}))

            excluded = _layer(run_root, repo)._excluded_from_corpus()

            self.assertIn((repo / "producer" / "receipt.json").resolve(), excluded)


class MutationControlTests(unittest.TestCase):
    """Do the tests above have teeth?

    Each test removes exactly one guard from the shipped source and asserts the
    behaviour that the guard was there to prevent comes back.  A guard that no mutation
    can expose is a guard nobody is testing.
    """

    def setUp(self):
        self.source = LAYER.read_text(encoding="utf-8")

    def test_removing_the_non_object_guard_reintroduces_the_crash(self):
        # The guard's whole effect is disarming the ``if not isinstance(doc, dict)``
        # branch that protects the ``doc.get()`` below.  Turning that branch off
        # (rather than deleting it, which would not compile) un-guards the crash site.
        needle = ('        if not isinstance(doc, dict):\n'
                  '            # A26-C1: a non-object provenance document')
        self.assertIn(needle, self.source, "A26-C1 guard not found -- the mutation control is stale")
        mutated = self.source.replace(
            needle, '        if False:  # MUTANT: guard disarmed\n'
                    '            # A26-C1: a non-object provenance document', 1)
        self.assertNotEqual(mutated, self.source, "the mutation did not apply")

        module = _load_layer_from_source(mutated)
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, '"not-an-object"')
            layer = module["ProvenanceLayer"](run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            with self.assertRaises(AttributeError):
                layer._excluded_from_corpus()

    def test_reverting_the_sources_guard_reintroduces_the_crash(self):
        """A26-C3's guard, reverted to the pre-fix ``or []`` form, must crash again."""
        needle = ('        raw_sources = doc.get("sources")\n'
                  '        for entry in (raw_sources if isinstance(raw_sources, list) else []):\n')
        self.assertIn(needle, self.source, "A26-C3 guard not found -- the mutation control is stale")
        mutated = self.source.replace(
            needle, '        for entry in (doc.get("sources") or []):\n', 1)
        self.assertNotEqual(mutated, self.source, "the mutation did not apply")

        module = _load_layer_from_source(mutated)
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, '{"sources": 5}')
            layer = module["ProvenanceLayer"](run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            with self.assertRaises(TypeError):
                layer._excluded_from_corpus()

    def test_removing_the_blank_locator_guard_reintroduces_the_repo_wide_walk(self):
        # ``and entry["locator"]`` would still short-circuit on the empty string, so the
        # mutation has to disarm the clause outright, not merely drop ``.strip()``.
        needle = 'and entry["locator"].strip()):'
        self.assertIn(needle, self.source, "A26-C2 guard not found -- the mutation control is stale")
        mutated = self.source.replace(needle, 'and True):  # MUTANT: blank locator allowed', 1)

        module = _load_layer_from_source(mutated)
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": ""}]}))
            # R03: with the blank guard disarmed, ``repo_root / ""`` is the repo root;
            # the SOURCE SCOPE guard is the second independent barrier, so to expose the
            # blank guard alone the repo must be an allowed source root (the world with
            # only one barrier).  This is the honest side effect R03 recorded.
            layer = module["ProvenanceLayer"](run_root, {}, 1, repo, corpus_roots=[],
                                              base_skipped=True, allowed_source_roots=[repo])

            walked = layer._excluded_from_corpus()

            self.assertTrue(walked, "the unguarded locator did not walk the repo root")


def _producer_config(repo: Path, roots: dict) -> None:
    """Write the producer roots config the layer reads (R03)."""
    path = repo / vrp.PRODUCER_ROOTS_CONFIG_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(roots), encoding="utf-8")


class R03SourceScopeTests(unittest.TestCase):
    """R03: the allowed source scope is DERIVED from producer configuration.

    The original R03 candidate hard-coded ``DEFAULT_ALLOWED_SOURCE_ROOTS`` = the default
    corpus roots plus ``.runtime/authoring/requests``.  That is a whitelist of the DEFAULT
    paths, so a producer that was EXPLICITLY REDIRECTED to a real production directory
    elsewhere was refused -- a false positive on a legitimate source.  These tests pin the
    rework: the roots come from what the producer DECLARES (``author.py`` ``PRODUCER_ROOTS``)
    and RECORDS (``.runtime/entity-create/provenance-roots.json``).  Each of the four
    locator classes keeps its own positive and negative example.
    """

    # -- positives ----------------------------------------------------------- #

    def test_a_legit_narrow_root_is_in_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            _write_anchor(run_root, json.dumps({"sources": []}))
            layer = _layer(run_root, repo)                       # allowed = [repo/"producer"]
            self.assertIsNone(layer._source_scope_defect((repo / "producer").resolve()))

    def test_an_explicitly_redirected_production_directory_is_in_scope(self):
        """THE REWORK: a redirected producer root must not be refused by a default whitelist.

        The producer materialises the roots it was TOLD at
        ``.runtime/entity-create/provenance-roots.json``.  Point them at a real directory
        OUTSIDE the repo and a locator under it must be in scope -- the original R03
        candidate (hard-coded repo-relative defaults) refused exactly this, which is the
        "default-root whitelist wrongly rejects an explicitly redirected production
        directory" defect this rework removes.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            production = tmp_path / "staging" / "receipts"       # a real, redirected tree
            production.mkdir(parents=True)
            _producer_config(repo, {key: str(production) for key in vrp.SOURCE_ROOT_KEYS})
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)

            layer = vrp.ProvenanceLayer(run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            self.assertIn(production.resolve(), layer.allowed_source_roots,
                          "the redirected root was not derived from the producer config")
            self.assertIsNone(layer._source_scope_defect((production / "sub").resolve()))

    def test_the_declared_producer_roots_are_read_from_author_py(self):
        """The roots come from ``author.py``'s own ``PRODUCER_ROOTS``, READ not restated."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            declared = tmp_path / "declared-production"
            declared.mkdir(parents=True)
            author = repo / vrp.PRODUCER_ROOTS_MODULE_RELATIVE
            author.parent.mkdir(parents=True)
            author.write_text(
                "PRODUCER_ROOTS = {\n"
                "    'journalRoot': %r,\n"
                "    'queueRoot': %r,\n"
                "    'receiptRoot': %r,\n"
                "    'nativeRoot': %r,\n"
                "}\n" % (str(declared), str(declared), str(declared), str(declared)),
                encoding="utf-8")
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)

            layer = vrp.ProvenanceLayer(run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            self.assertIn(declared.resolve(), layer.allowed_source_roots)

    def test_the_real_producers_own_locators_are_in_scope(self):
        """Regression: the two locators ``write_run_provenance_input.py`` emits are in scope.

        ``<receiptRoot>/<runId>/receipts`` and ``<queueRoot>`` -- measured against the
        layer's OWN derived roots, never a restated list.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            receipt_root = repo / ".runtime/editor-bridge/runs"
            queue_root = repo / ".runtime/editor-bridge/elevated-queue"
            (receipt_root / RUN_ID / "receipts").mkdir(parents=True)
            queue_root.mkdir(parents=True)
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)

            layer = vrp.ProvenanceLayer(run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            self.assertIsNone(
                layer._source_scope_defect((receipt_root / RUN_ID / "receipts").resolve()))
            self.assertIsNone(layer._source_scope_defect(queue_root.resolve()))

    # -- negatives ----------------------------------------------------------- #

    def test_out_of_scope_locators_are_refused_by_name(self):
        """``.`` / ``..`` / an ancestor / an absolute escape are each OUT_OF_SCOPE."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            outside = tmp_path / "scratch-outside"               # a directory outside the repo
            outside.mkdir()
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)

            layer = vrp.ProvenanceLayer(run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)
            for target in (repo, repo.parent, repo / ".runtime", outside):
                with self.subTest(target=str(target)):
                    self.assertEqual(layer._source_scope_defect(target.resolve()),
                                     "PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE")

    def test_dot_and_parent_do_not_walk_the_repo(self):
        """Only an OUT-OF-SCOPE locator is skipped, so ``.`` no longer walks the whole repo."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            for locator in (".", "..", ".runtime", "..\\.."):
                with self.subTest(locator=locator):
                    _write_anchor(run_root, json.dumps({"sources": [
                        {"sourceId": "s", "kind": "helper-receipt", "locator": locator}]}))
                    self.assertEqual(_layer(run_root, repo)._excluded_from_corpus(), frozenset())

    def test_a_locator_covering_the_audited_run_is_refused(self):
        """A locator inside a producer root that CONTAINS the run is refused, and bounded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            nested_run = repo / "producer" / "runs" / RUN_ID
            nested_run.mkdir(parents=True)
            _write_anchor(nested_run, json.dumps({"sources": [
                {"sourceId": "s", "kind": "helper-receipt", "locator": "producer"}]}))

            layer = _layer(nested_run, repo)                     # allowed = [repo/"producer"]

            self.assertEqual(layer._source_scope_defect((repo / "producer").resolve()),
                             "PROVENANCE_SOURCE_LOCATOR_COVERS_RUN")
            # COVERS_RUN is still EXCLUDED (bounded, and dropping the run is the point),
            # so the corpus cannot be emptied by the exclusion and refused for the wrong
            # reason -- unlike the OUT-OF-SCOPE case above.
            self.assertTrue(layer._excluded_from_corpus())

    def test_a_binding_to_an_out_of_scope_source_still_fails(self):
        """The refusal is not traded for a cheaper one: the crosscheck still fails."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            doc = {"sources": [{"sourceId": "s", "kind": "helper-receipt", "locator": ".",
                                "directoryManifestSha256": "0" * 64}]}
            _write_anchor(run_root, json.dumps(doc))

            layer = _layer(run_root, repo)
            layer.corpus = vrp.ExternalCorpus([], frozenset())
            layer.frozen_gates = {}                              # classify_target needs these
            layer.frozen_cases = {}
            sources = layer.load_sources(doc)

            self.assertIn("PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE", _codes(layer.defects))
            self.assertEqual(sources["s"]["scalars"], set())
            layer.bind_one("gate:S00/session", "s", sources, RUN_ID)
            self.assertIn("PROVENANCE_CROSSCHECK_FAILED", _codes(layer.defects))

    def test_a_config_inside_the_audited_run_is_not_honoured(self):
        """A producer config the RUN could write must not widen the scope (self-attestation).

        Two sides.  When the run root CONTAINS the config path the config is the run
        describing itself and is refused; when it does not, the same config is honoured.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            evil = tmp_path / "evil"
            evil.mkdir()
            _producer_config(repo, {key: str(evil) for key in vrp.SOURCE_ROOT_KEYS})

            # run root == repo: the config path is inside it -> refused
            inside = vrp.ProvenanceLayer(repo, {}, 1, repo, corpus_roots=[], base_skipped=True)
            self.assertNotIn(evil.resolve(), inside.allowed_source_roots)

            # control: a run root that does NOT contain the config honours it
            other = tmp_path / "run" / RUN_ID
            other.mkdir(parents=True)
            outside = vrp.ProvenanceLayer(other, {}, 1, repo, corpus_roots=[], base_skipped=True)
            self.assertIn(evil.resolve(), outside.allowed_source_roots)

    def test_cli_reports_an_out_of_scope_locator(self):
        """End to end: the CLI refuses ``.`` by name with a verdict body, no traceback."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / RUN_ID
            _write_anchor(run_root, json.dumps({
                "kind": "entity-create-run-provenance", "schemaVersion": 1,
                "runId": RUN_ID, "contractPin": {"sha256": "0" * 64},
                "sources": [{"sourceId": "s", "kind": "helper-receipt", "locator": "."}],
                "bindings": []}))
            empty_corpus = tmp_path / "corpus"
            empty_corpus.mkdir()

            proc = subprocess.run(
                [sys.executable, "-B", str(LAYER), str(run_root),
                 "--corpus-roots", str(empty_corpus), "--quiet"],
                capture_output=True, text=True)

            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            verdict = json.loads(proc.stdout)
            self.assertIn("PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE",
                          _codes(verdict["provenanceDefects"]))

    # -- mutation controls --------------------------------------------------- #

    def test_removing_the_scope_guard_reaccepts_an_out_of_scope_source(self):
        """The scope guard is what refuses the negative cases; disarming it re-accepts them."""
        source = LAYER.read_text(encoding="utf-8")
        needle = ("            scope_code = self._source_scope_defect(resolved)\n"
                  "            if scope_code is not None:\n")
        self.assertIn(needle, source, "R03 scope guard not found -- mutation control is stale")
        mutated = source.replace(
            needle,
            "            scope_code = self._source_scope_defect(resolved)\n"
            "            if False:  # MUTANT: scope guard disarmed\n", 1)
        self.assertNotEqual(mutated, source, "the mutation did not apply")

        module = _load_layer_from_source(mutated)
        with tempfile.TemporaryDirectory() as tmp:
            repo = _synthetic_repo(Path(tmp))
            run_root = Path(tmp) / RUN_ID
            doc = {"sources": [{"sourceId": "s", "kind": "helper-receipt", "locator": ".",
                                "directoryManifestSha256": "0" * 64}]}
            _write_anchor(run_root, json.dumps(doc))
            layer = module["ProvenanceLayer"](run_root, {}, 1, repo, corpus_roots=[],
                                              base_skipped=True,
                                              allowed_source_roots=[repo / "producer"])
            sources = layer.load_sources(doc)

            self.assertNotIn("PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE",
                             {d["code"] for d in layer.defects})
            self.assertTrue(sources["s"]["scalars"],
                            "the unguarded locator did not scan the repository root")

    def test_reverting_to_the_hardcoded_default_whitelist_refuses_a_redirected_producer(self):
        """THE REWORK'S OWN MUTATION: a default-only whitelist re-breaks the redirect case.

        Neutralising the two DERIVATION calls restores the original R03 behaviour (the
        fallback defaults only), and the explicitly redirected production directory is
        refused again.  This is the counterexample that shows the derivation is load
        bearing, not decorative.
        """
        source = LAYER.read_text(encoding="utf-8")
        needle = ("        roots.extend(self._declared_producer_roots())\n"
                  "        roots.extend(self._configured_producer_roots())\n")
        self.assertIn(needle, source, "the derivation not found -- mutation control is stale")
        mutated = source.replace(
            needle,
            "        roots.extend(())  # MUTANT: hard-coded default whitelist only\n"
            "        roots.extend(())\n", 1)
        self.assertNotEqual(mutated, source, "the mutation did not apply")

        module = _load_layer_from_source(mutated)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            production = tmp_path / "staging" / "receipts"
            production.mkdir(parents=True)
            _producer_config(repo, {key: str(production) for key in vrp.SOURCE_ROOT_KEYS})
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)
            layer = module["ProvenanceLayer"](run_root, {}, 1, repo, corpus_roots=[],
                                              base_skipped=True)

            self.assertNotIn(production.resolve(), layer.allowed_source_roots)
            self.assertEqual(layer._source_scope_defect((production / "sub").resolve()),
                             "PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE")

    def test_derivation_never_admits_the_repository_root(self):
        """Guard rail: even with a redirect present, ``.`` (the repo root) is not in scope."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = _synthetic_repo(tmp_path)
            production = tmp_path / "staging"
            production.mkdir()
            _producer_config(repo, {key: str(production) for key in vrp.SOURCE_ROOT_KEYS})
            run_root = tmp_path / "run" / RUN_ID
            run_root.mkdir(parents=True)

            layer = vrp.ProvenanceLayer(run_root, {}, 1, repo, corpus_roots=[], base_skipped=True)

            self.assertEqual(layer._source_scope_defect(repo.resolve()),
                             "PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE")


if __name__ == '__main__':
    unittest.main()
