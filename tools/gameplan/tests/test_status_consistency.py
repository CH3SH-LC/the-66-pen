"""Master status-consistency check (#8): the drift guards themselves must stay ALIVE.

A family of guards now holds the documents to the code, each guarding one invariant:

  * ``test_doctrine``             CLAUDE.md's load-bearing claims vs the bridge build,
                                  the ``command_route`` table, the field-7 codec
  * ``test_no_false_uniqueness``  refuted "the only one such value" prose stays dead
  * ``test_no_stale_op_count``    no document states a bare bridge op count
  * ``test_repo_consistency``     the doc-vs-code invariants whose drift bit this session
  * ``test_evidence_discipline``  a capability claim carries a citation or a hedge
  * ``test_verification_claims``  a "verified" claim cites a receipt that exists on disk

Every one of them has been broken at least once — ``docs/gameplan/SESSION-LESSONS.md`` §二
records a verifier defeating ``test_no_false_uniqueness`` (its normaliser kept the comment
marker and its negative control spliced a fabricated single line), and ``PROGRESS.md:14-23``
records a verifier defeating ``test_no_stale_op_count`` (it stripped backticked spans before
matching, so the commonest Markdown shape `` `ValidateSet` = **135** `` was never examined).
Each was repaired.  But a *repaired* guard can still vanish silently: rename it, move it
under a pruned directory, or gut it so pytest collects nothing, and the suite goes green
while the invariant it protected is unchecked.  Nothing in the suite caught *that*.  This
file does — it is the teeth for the teeth.

It asserts three things about every guard in the registry below, and **nothing about their
verdicts** (what each guard decides is that guard's own business):

  1. the file EXISTS at its registered path;
  2. it IMPORTS (a syntax error or a bad top-level import would otherwise surface only as a
     whole-suite collection error, which is easy to lose among 700 passing tests);
  3. it is COLLECTED — discovered by ``scripts/run-tests.ps1``'s walk (its name matches the
     runner's ``^(test[-_].*|.*_test)\\.py$`` and no path segment is in the runner's prune
     set) AND actually collected by pytest with at least one test.

A fourth test does NOT assert, only REPORTS: which guards carry a **negative control** (a
case the guard must catch — a control-shaped test name, or an explicit marker) and which do
not.  A guard with no negative control is a guard that has never been shown to fail on the
input it exists for; the report names them so the gap is visible, but a missing control is
not itself a build break.

Proven, not assumed
-------------------
``GuardLivenessHasTeeth`` attacks the machinery with the REAL failure shapes a guard
vanishes by, not a convenient one:

  * a **deleted** file (the registry path stops existing);
  * a **renamed** file (``…/doctrine_renamed.py`` no longer matches the runner's pattern, and
    a file moved under ``.runtime/`` is pruned) — the exact shapes that make a guard drop out
    of discovery without a single red test;
  * an **uncollectable** file — the real ``tools/beyond-save/test_keep_registered.py``, which
    pytest collects 0 tests from (the "looks like a test, protects nothing" shape the
    ``TEST-AUDIT`` names), used as the fixture so the collector is exercised on real input;
  * a **missing** path — pytest itself errors (rc 4).

The controls call the SAME predicates the checks above call, so a broken predicate cannot
pass the checks on a green technicality.

Read-only, offline: the file opens are reads; the only subprocess is
``pytest --collect-only`` over the guard files, which executes no test body and touches no
bridge, game, editor, helper, or save.

Run::

    python -B -m unittest tools.gameplan.tests.test_status_consistency
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: The registry.  Each entry is ``(repo-relative path, invariant it protects)``.  This is
#: the authority for "which guards exist"; a guard that is renamed or relocated off its
#: registered path fails :meth:`GuardsAreAlive.test_every_guard_file_exists` rather than
#: silently dropping out of the suite.
GUARDS: tuple[tuple[str, str], ...] = (
    ("tools/gameplan/tests/test_doctrine.py",
     "CLAUDE.md's load-bearing claims vs the bridge build / command_route / field-7 codec"),
    ("tools/gameplan/tests/test_no_false_uniqueness.py",
     "refuted 'only one such value' prose stays dead in the five owned source files"),
    ("tools/gameplan/tests/test_no_stale_op_count.py",
     "no document states a bare bridge op count without a pointer to test_doctrine"),
    ("tools/gameplan/tests/test_dict_nodes_not_absent.py",
     "the refuted 'no dictionary node exists' prose stays dead; the dict nodes stay in the store"),
    ("tools/gameplan/tests/test_repo_consistency.py",
     "the doc-vs-code invariants that drifted (compiled split, field-7 reader, save quotes, goldens)"),
    ("tools/gameplan/tests/test_evidence_discipline.py",
     "a capability claim in a status doc carries a citation or a hedge"),
    ("tools/gameplan/tests/test_verification_claims.py",
     "a 'verified' claim cites a receipt that exists on disk"),
    ("tools/gameplan/tests/test_status_consistency.py",
     "this meta-guard: the guards above exist, import, and are collected"),
)
GUARD_PATHS: tuple[str, ...] = tuple(rel for rel, _ in GUARDS)

# --------------------------------------------------------------------------- #
# scripts/run-tests.ps1's discovery, mirrored verbatim
# --------------------------------------------------------------------------- #
#: The runner's prune set (``$pruneNames`` in scripts/run-tests.ps1).  A suite under one of
#: these directory names is never walked, so a guard moved into one is never collected.
_PRUNE = frozenset({
    ".git", ".runtime", "vendor", "node_modules", "__pycache__", ".pytest_cache",
    ".venv", "venv", "dist", "build", ".idea", ".vscode",
})
#: The runner's python-test filename pattern (``$pyNamePattern``).
_PY_NAME_RE = re.compile(r"^(test[-_].*|.*_test)\.py$")


def runner_discovers(rel: str) -> bool:
    """True iff ``scripts/run-tests.ps1``'s walk would place *rel* in a python suite.

    The two conditions the runner applies to a file: its name matches the runner's pattern,
    and no *directory* on its path is in the runner's prune set.  (Path separators are
    normalised to ``/`` so the same predicate serves a repo-relative posix path.)
    """
    p = Path(rel.replace("\\", "/"))
    if not _PY_NAME_RE.match(p.name):
        return False
    return not any(part in _PRUNE for part in p.parts[:-1])


def _dotted(rel: str) -> str:
    """``tools/gameplan/tests/test_x.py`` -> ``tools.gameplan.tests.test_x``."""
    return rel.replace("\\", "/")[:-3].replace("/", ".")


def import_guard(rel: str):
    """Import a guard module by its repo-relative path (the repo root is on ``sys.path``)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return importlib.import_module(_dotted(rel))


def collect_with_pytest(rels: tuple[str, ...]) -> tuple[int, str]:
    """Run ``pytest --collect-only`` over *rels*; return ``(returncode, output)``.

    ``--collect-only`` imports each module (so a broken guard surfaces) but executes no test
    body, so this is side-effect free.  Output is the combined stdout+stderr.
    """
    argv = [sys.executable, "-m", "pytest", "--collect-only", "-q",
            "-p", "no:cacheprovider", *rels]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(argv, cwd=str(REPO), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300)
    return proc.returncode, f"{proc.stdout or ''}\n{proc.stderr or ''}"


def _pytest_available() -> bool:
    try:
        import pytest  # noqa: F401,PLC0415
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #

class GuardsAreAlive(unittest.TestCase):
    """DRIFT DETECTOR — reads every registered guard file and the runner's rules."""

    def test_registry_is_non_empty_and_unique(self):
        """A guard list that is empty or has duplicate paths cannot protect anything."""
        self.assertTrue(GUARD_PATHS, "the guard registry is empty")
        self.assertEqual(
            len(GUARD_PATHS), len(set(GUARD_PATHS)),
            f"duplicate entries in the guard registry: {GUARD_PATHS}")

    def test_every_guard_file_exists(self):
        """A renamed or deleted guard must not vanish — its registered path must exist."""
        missing = [rel for rel in GUARD_PATHS if not (REPO / rel).is_file()]
        self.assertEqual(
            missing, [],
            "these registered guards no longer sit at their path (renamed, moved, or "
            f"deleted) — restore them or update the registry:\n  " + "\n  ".join(missing))

    def test_every_guard_imports(self):
        """A guard with a syntax error / bad top-level import must fail loudly here."""
        for rel in GUARD_PATHS:
            with self.subTest(guard=rel):
                try:
                    mod = import_guard(rel)
                except Exception as exc:  # noqa: BLE001 — a broken guard is the point
                    self.fail(f"{rel} failed to import: {exc!r}")
                self.assertTrue(
                    getattr(mod, "__file__", "").replace("\\", "/").endswith(rel),
                    f"{rel} imported but its module __file__ is {getattr(mod, '__file__', None)!r}")

    def test_every_guard_is_discovered_by_the_suite_runner(self):
        """Each guard must satisfy ``scripts/run-tests.ps1``'s walk, or it is never run."""
        undiscovered = [rel for rel in GUARD_PATHS if not runner_discovers(rel)]
        self.assertEqual(
            undiscovered, [],
            "these guards would be SKIPPED by scripts/run-tests.ps1 (name does not match "
            "^(test[-_].*|.*_test)\\.py$ or a path segment is in the runner's prune set):\n  "
            + "\n  ".join(undiscovered))

    def test_every_guard_is_collected_by_pytest(self):
        """Each guard must actually collect ≥1 test — not just be discoverable on disk."""
        if not _pytest_available():
            self.skipTest("pytest is not importable; cannot verify collection")
        rc, out = collect_with_pytest(GUARD_PATHS)
        self.assertEqual(
            rc, 0,
            "pytest failed to collect the registered guards (exit "
            f"{rc}); a guard that cannot be collected is a guard that has vanished:\n{out[-2000:]}")
        for rel in GUARD_PATHS:
            with self.subTest(guard=rel):
                self.assertIn(
                    f"{rel}::", out,
                    f"{rel} collected NO tests (pytest printed no nodeid for it) — the "
                    "guard is present but protects nothing")


class GuardLivenessHasTeeth(unittest.TestCase):
    """Negative controls — the liveness machinery is attacked with the REAL failure shapes.

    Each control drives the SAME predicate the checks above use, so a predicate that is
    quietly always-False (and thus lets every guard pass the "exists/collected" checks on a
    green technicality) is caught here.
    """

    def test_the_runner_discovery_predicate_bites_both_ways(self):
        """A renamed / relocated guard drops out of discovery; the real path stays in."""
        # the real names ARE discovered — so the predicate is not vacuously False
        for rel in GUARD_PATHS:
            self.assertTrue(runner_discovers(rel), f"the runner would not discover {rel}")
        # a rename that keeps the file but loses the pattern is NO LONGER discovered
        for renamed in (
            "tools/gameplan/tests/doctrine_renamed.py",
            "tools/gameplan/tests/test_doctrine.py.bak",
            "tools/gameplan/tests/doctrine_test.txt",
        ):
            with self.subTest(renamed=renamed):
                self.assertFalse(
                    runner_discovers(renamed),
                    f"{renamed} would still be discovered — a renamed guard could vanish "
                    "without a red test")
        # a move under a pruned directory is NO LONGER discovered either
        for pruned in (
            ".runtime/tests/test_doctrine.py",
            "tools/gameplan/__pycache__/test_doctrine.py",
        ):
            with self.subTest(pruned=pruned):
                self.assertFalse(
                    runner_discovers(pruned),
                    f"{pruned} would still be discovered — a guard moved into a pruned "
                    "tree could vanish without a red test")

    def test_a_missing_guard_path_is_reported_missing(self):
        """The existence predicate (and pytest) both reject a path that is not there."""
        bogus = "tools/gameplan/tests/test_zzz_never_existed.py"
        self.assertFalse((REPO / bogus).is_file(),
                         "the fixture path unexpectedly exists; pick another")
        if not _pytest_available():
            self.skipTest("pytest is not importable; cannot check the collector's error")
        rc, _ = collect_with_pytest((bogus,))
        self.assertNotEqual(
            rc, 0,
            "pytest reported success for a guard path that does not exist — a vanished "
            "guard would be reported as collected")

    def test_an_uncollectable_file_is_not_reported_as_collected(self):
        """A file with no tests must NOT count as collected — on the real fixture.

        ``tools/beyond-save/test_keep_registered.py`` really exists and pytest really
        collects 0 tests from it (``docs/gameplan/SUITE-HEALTH.md`` §四 / ``TEST-AUDIT.md``
        §5): the "looks like a test, protects nothing" shape.  If the collector ever
        reported this file as collected, the ``every_guard_is_collected`` check above would
        pass on a guard gutted the same way.
        """
        fixture = "tools/beyond-save/test_keep_registered.py"
        if not (REPO / fixture).is_file():
            self.skipTest(f"the zero-collect fixture {fixture} is gone; cannot check")
        if not _pytest_available():
            self.skipTest("pytest is not importable; cannot check the collector")
        rc, out = collect_with_pytest((fixture,))
        self.assertNotEqual(
            rc, 0,
            f"{fixture} collects 0 tests, yet the collector reported exit 0 — an "
            "empty guard would be counted as collected")
        self.assertNotIn(
            f"{fixture}::", out,
            f"{fixture} produced a nodeid despite collecting nothing")


# --------------------------------------------------------------------------- #
# Negative-control inventory (REPORT only — a missing control is not a failure)
# --------------------------------------------------------------------------- #

#: Tokens in a test's NAME that mark it a negative/positive control or a teeth check.
_CONTROL_TOKENS = re.compile(
    r"control|vacuous|not_vacuous|flag|offend|synthetic|negative|would_be_caught|"
    r"real_document|real_file|spliced|planted|corrupt|broken|repro|teeth|mutation|"
    r"bites|is_not_",
    re.IGNORECASE,
)
#: An explicit in-source marker a guard may carry instead of a control-shaped name.
_CONTROL_MARKER = re.compile(r"NEGATIVE CONTROL|negative[- ]control|#\s*control\b",
                             re.IGNORECASE)
_DEF_RE = re.compile(r"^\s*def (test_\w+)", re.MULTILINE)


def control_evidence(source: str) -> list[str]:
    """Control-looking test names in *source*, plus ``'<marker>'`` if an explicit marker is present.

    This is the single predicate the inventory uses.  A guard "has a negative control" iff
    this returns a non-empty list.  Empty for ordinary source — see
    :meth:`NegativeControlInventory.test_the_control_detector_is_not_vacuous`.
    """
    found = [name for name in _DEF_RE.findall(source) if _CONTROL_TOKENS.search(name)]
    if _CONTROL_MARKER.search(source):
        found.append("<marker>")
    return found


class NegativeControlInventory(unittest.TestCase):
    """Scans each guard for a negative control; REPORTS the ones without, never fails on them."""

    def test_the_control_detector_is_not_vacuous(self):
        """The detector must fire on a control and stay silent on ordinary code."""
        self.assertTrue(
            control_evidence("def test_the_scan_is_not_vacuous(self):\n"),
            "the detector misses a control-shaped test name")
        self.assertTrue(
            control_evidence("# NEGATIVE CONTROL: splice a lie back in\n"),
            "the detector misses the explicit marker")
        self.assertFalse(
            control_evidence("def test_plain_assertion(self):\n    self.assertTrue(True)\n"),
            "the detector fires on ordinary code")

    def test_report_which_guards_lack_a_negative_control(self):
        """Print the per-guard control inventory; do not fail on a guard that lacks one.

        The scan must cover every registered guard (asserted), but whether a guard carries a
        control is reported only — the guards that need one are named in the output so a
        reader can act, rather than turning a bookkeeping gap into a red suite.
        """
        evidence: dict[str, list[str]] = {}
        for rel in GUARD_PATHS:
            evidence[rel] = control_evidence((REPO / rel).read_text(encoding="utf-8"))

        # the scan really visited every guard (not an empty loop)
        self.assertEqual(
            len(evidence), len(GUARD_PATHS),
            "the control scan did not cover every registered guard")

        lacking = [rel for rel in GUARD_PATHS if not evidence[rel]]
        lines = ["negative-control inventory (report only; a missing control is not a failure):"]
        for rel, invariant in GUARDS:
            tag = "HAS " if evidence[rel] else "NONE"
            shown = ", ".join(evidence[rel]) if evidence[rel] else "-"
            lines.append(f"  {tag} {rel}  [{shown}]")
        if lacking:
            lines.append("  guards lacking a negative control: " + ", ".join(lacking))
        print("\n".join(lines))

        # Guard-against-blindness (the repo's own "the 0 must not be an empty pattern" rule):
        # the detector must find a control in at least one registered guard, else it has
        # silently stopped detecting and every "HAS" would be a lie.
        self.assertTrue(
            any(evidence.values()),
            "no registered guard's negative control was detected — the detector has gone "
            "blind, so the whole report is meaningless")


if __name__ == "__main__":
    unittest.main()
