"""The write-review baseline must be captured AFTER the graph work, not before.

WHY THIS FILE EXISTS (the 2026-10-11 refusal)
---------------------------------------------
A `save` was refused twice.  The second refusal carried `actionStatus 6`,
`nativeStatus -1`, `error "Native save status was not success"`, and
`gilChanged {1073741842: false}` — and it was NOT an encoding bug, it was ORDERING.

The reviewed write profile compiles the BASELINE SNAPSHOT's heap identity:
`currentContext` plus each entity's `owner/config/context` pointers
(`tools/game-executor/native/game_scene_action.cpp:109`, `BaselineIdentityMatches()`).
Bridge graph work SHIFTS the game's heap, so a baseline captured BEFORE the graph
dispatch no longer matches at save time:

    12:30 baseline  currentContext = 0x700135fac10   (captured before the graph build)
    12:39 save      currentContext = 0x70025e5a990   (all 12 pointer tuples differ)

    => BaselineIdentityMatches() returns false  => actionStatus 6 / nativeStatus -1

The fresh-baseline retry at 12:44 (baseline captured AFTER the graph work) matched
(0x70025e5a990 == 0x70025e5a990) and saved.  The refusal was SAFE: the receipt shows
`called: 0` and `nativeStarted: true`, so it refused BEFORE any game call — the cost
is one cycle, not data.

WHAT THIS TEST PINS
-------------------
A runbook that documents a write procedure carries three ordered phase markers
(the marker is the contract — keep it):

    <!-- phase:graph-dispatch -->
    <!-- phase:baseline-capture -->
    <!-- phase:native-save -->

and it must not FREEZE a concrete `--baseline-run` value anywhere.  Two rules:

  R1 (position)  a `--baseline-run` inside a command block BEFORE the graph-dispatch
                 marker is the shape of the 2026-10-11 refusal;
  R2 (value)     a CONCRETE `--baseline-run` value (a real run path / id, NOT a
                 ``<PLACEHOLDER>``) is a defect WHEREVER it sits.

WHY R2 EXISTS (2026-10-11 second pass)
--------------------------------------
R1 alone cannot bite the real defect.  The repro that exposed this was a stale
hard-coded id (``--baseline-run .runtime/.../inspect/<old>``) placed AFTER the graph
marker: R1 returned [].  The defect is not the value's POSITION in the doc — it is that
a concrete id written into a document can only ever have been captured at DOC-WRITING
time, hence strictly BEFORE the (future) graph dispatch it is required to follow.  A
frozen concrete id is therefore stale BY CONSTRUCTION, and the honest static rule is to
forbid it outright: the value must stay a placeholder (``<FRESH_RUN>``) substituted at
run time from a discovery that itself sits after graph-dispatch.
``TemplateNeverFreezesABaselineRun`` keeps the shipped template on that side of the line.

Honest scope: this is still a STATIC check over markdown.  It cannot see prose that
describes the order wrongly without a marker, and it cannot verify the capture TIME of
any run id named only in prose.  What it CAN do — and R2 does — is refuse to let any
concrete id into the document at all, which is the strongest thing a text check can
honestly say about a value's freshness.  The checker is exercised on synthetic BAD
documents (both the pre-marker shape and the after-marker stale concrete value) so its
teeth are proven, not assumed.

Pure reads only: no bridge, no native call, no game/editor contact, nothing written.

Run::

    python -B -m unittest tools.gameplan.tests.test_baseline_order
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: The canonical, tracked runbook and the tracked template.  Both must exist.
REQUIRED_RUNBOOKS = (
    REPO / "docs" / "gameplan" / "RUNBOOK.md",
    REPO / "docs" / "gameplan" / "RUNBOOK-TEMPLATE.md",
)
#: A scratch runbook that carried the actual bug.  `.runtime/` is git-ignored, so it
#: is only audited when present (skip, loudly, otherwise).
OPTIONAL_RUNBOOKS = (
    REPO / ".runtime" / "scratch" / "WAVE29H-RUNBOOK.md",
)

#: Required phases, in the only order that is correct.
PHASES = ("graph-dispatch", "baseline-capture", "native-save")

_PHASE_RE = re.compile(r"<!--\s*phase:([a-z][a-z\-]*)")
_BASELINE_VALUE_RE = re.compile(r"--baseline-run\b")
#: The value token following ``--baseline-run`` (``=` or whitespace separated).
_BASELINE_TOKEN_RE = re.compile(r"--baseline-run(?:=|\s+)(\S+)")
#: A value is a PLACEHOLDER — substituted at run time, hence never provably stale — when
#: the WHOLE token is one of: ``<NAME>``, ``$NAME``, ``${NAME}``, ``{{NAME}}``, an
#: ellipsis.  Anything else (a real path, a real uuid, ``…/inspect/<old>``) is CONCRETE.
_PLACEHOLDER_RE = re.compile(
    r"^(?:"
    r"<[^<>\s]+>"
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"
    r"|\{\{[^}\s]+\}\}"
    r"|…|\.\.\."
    r")$"
)


def _code_block_lines(text: str) -> list[tuple[int, str]]:
    """(1-based line number, line) for every line INSIDE a ``` fenced code block.

    A documented ``--baseline-run`` VALUE lives in a shell command, i.e. inside a
    fence.  Prose that merely *names* the flag (to state the rule) is outside a fence
    and must not be flagged — scoping to fences is what keeps this check honest
    instead of brittle.
    """
    inside: list[tuple[int, str]] = []
    open_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            open_fence = not open_fence
            continue
        if open_fence:
            inside.append((lineno, line))
    return inside


def _baseline_values(line: str) -> list[str]:
    """Every VALUE token given to ``--baseline-run`` on ``line`` ([] if none).

    Reads both ``--baseline-run=value`` and ``--baseline-run value``.  A token that is
    itself another flag (``--baseline-kind``) or a shell line continuation is not a
    value, so a bare flag mid-command yields no value.
    """
    values: list[str] = []
    for m in _BASELINE_TOKEN_RE.finditer(line):
        token = m.group(1)
        if token.startswith("-") or token == "\\":
            continue
        values.append(token)
    return values


def _is_concrete(value: str) -> bool:
    """True when ``value`` is NOT a pure placeholder, i.e. frozen into the document."""
    return _PLACEHOLDER_RE.match(value) is None


def audit_runbook(text: str) -> list[str]:
    """Return a list of problems with ``text`` as a runbook ([] == ordered correctly).

    Kept a pure function of the text so the synthetic self-tests below can prove it
    has teeth without touching the real files.
    """
    problems: list[str] = []

    order = [m.group(1) for m in _PHASE_RE.finditer(text)]
    for phase in PHASES:
        count = order.count(phase)
        if count != 1:
            problems.append(
                f"phase marker '{phase}' appears {count} time(s); exactly 1 is required")

    if all(order.count(p) == 1 for p in PHASES):
        idx = {p: order.index(p) for p in PHASES}
        if not (idx["graph-dispatch"] < idx["baseline-capture"] < idx["native-save"]):
            problems.append(
                "phase markers are out of order: "
                f"{idx} — required graph-dispatch < baseline-capture < native-save")

    gd = text.find("<!-- phase:graph-dispatch")
    head_line_count = text[:gd].count("\n") if gd >= 0 else None  # lines before the marker

    for lineno, line in _code_block_lines(text):
        if _BASELINE_VALUE_RE.search(line) and head_line_count is not None \
                and lineno <= head_line_count:
            # R1 — the historical shape: a value documented up front.
            problems.append(
                f"line {lineno}: '--baseline-run' is documented in a command block "
                f"BEFORE the graph-dispatch phase (the shape of the 2026-10-11 "
                f"refusal): {line.strip()!r}")
        for value in _baseline_values(line):
            if not _is_concrete(value):
                continue  # a placeholder is substituted at run time; not stale
            # R2 — a CONCRETE value frozen anywhere.  This is the shape R1 cannot see:
            # the adversary's stale `--baseline-run .../inspect/<old>` sat AFTER the
            # marker, so position alone returned [].
            problems.append(
                f"line {lineno}: '--baseline-run' is frozen to the CONCRETE value "
                f"{value!r}. A run id written into a document predates the graph "
                f"dispatch it must follow, so it is stale by construction, wherever it "
                f"sits. Substitute a placeholder (<FRESH_RUN>) filled at run time from a "
                f"discovery that ran AFTER graph-dispatch.")

    return problems


class AuditHasTeeth(unittest.TestCase):
    """Prove the checker FAILS on the bad shapes before trusting it on the real docs."""

    _GOOD = (
        "# runbook\n"
        "<!-- phase:graph-dispatch -->\n"
        "## build the graph\n"
        "```bash\n"
        "python … graph build-plan\n"
        "```\n"
        "<!-- phase:baseline-capture -->\n"
        "<!-- phase:native-save -->\n"
        "## save\n"
        "```bash\n"
        "python … orchestrate_write_review.py --baseline-run <FRESH_RUN>\n"
        "python … save\n"
        "```\n"
    )

    def test_good_document_has_no_problems(self):
        self.assertEqual(audit_runbook(self._GOOD), [])

    def test_prose_mention_of_the_flag_before_the_graph_phase_is_NOT_flagged(self):
        """A rule that merely NAMES the flag must not trip the check (anti-brittleness)."""
        prose = ("# runbook\n"
                 "> the value of `--baseline-run` must not be set before the graph phase\n"
                 + self._GOOD)
        self.assertEqual(audit_runbook(prose), [])

    def test_baseline_in_a_command_block_before_graph_phase_is_caught(self):
        """The exact mistake: a baseline VALUE documented up front, graph phase later."""
        bad = (
            "## reconnaissance\n"
            "```bash\n"
            "python … orchestrate_write_review.py --baseline-run <STALE_RUN>\n"
            "```\n"
        ) + self._GOOD
        problems = audit_runbook(bad)
        self.assertTrue(
            any("BEFORE the graph-dispatch" in p for p in problems),
            f"checker missed a pre-graph baseline value: {problems}")

    def test_reordered_phases_are_caught(self):
        bad = self._GOOD.replace(
            "<!-- phase:baseline-capture -->\n<!-- phase:native-save -->\n",
            "<!-- phase:native-save -->\n<!-- phase:baseline-capture -->\n",
        )
        self.assertTrue(
            any("out of order" in p for p in audit_runbook(bad)),
            "checker missed reordered phases")

    def test_missing_phase_is_caught(self):
        bad = self._GOOD.replace("<!-- phase:baseline-capture -->\n", "")
        self.assertTrue(
            any("'baseline-capture' appears 0" in p for p in audit_runbook(bad)),
            "checker missed a missing phase marker")


class AuditCatchesStaleBaselineAfterTheGraphPhase(unittest.TestCase):
    """R2 — the adversary's repro: a concrete stale id AFTER the graph marker.

    R1 (position) returns [] on this document; only the value rule catches it.  The
    first case below pins that fact so the reason R2 exists cannot silently rot.
    """

    _STALE = ".runtime/scratch/wave29h/inspect/20261011-123012-deadbeef"

    def _doc(self) -> str:
        return AuditHasTeeth._GOOD.replace("--baseline-run <FRESH_RUN>",
                                           "--baseline-run " + self._STALE)

    def test_the_stale_value_really_sits_after_the_marker(self):
        doc = self._doc()
        marker = doc.find("<!-- phase:graph-dispatch")
        gd_line = doc[:marker].count("\n") + 1
        stale_line = next(n for n, l in enumerate(doc.splitlines(), 1)
                          if self._STALE in l)
        self.assertGreater(stale_line, gd_line,
                           "the repro is only interesting when the value is AFTER the marker")

    def test_concrete_baseline_after_marker_is_caught(self):
        problems = audit_runbook(self._doc())
        self.assertTrue(
            any("CONCRETE value" in p for p in problems),
            f"checker missed an after-marker stale concrete baseline: {problems}")

    def test_placeholder_baseline_after_marker_is_not_flagged(self):
        self.assertEqual(audit_runbook(AuditHasTeeth._GOOD), [])

    def test_path_containing_a_placeholder_looking_segment_is_still_concrete(self):
        """`…/inspect/<old>` is a path, not a placeholder — it must be flagged."""
        doc = AuditHasTeeth._GOOD.replace("--baseline-run <FRESH_RUN>",
                                          "--baseline-run …/inspect/<old>")
        self.assertTrue(
            any("CONCRETE value" in p for p in audit_runbook(doc)),
            "checker accepted a concrete path that merely contains an angled segment")


class RealRunbooksAreOrdered(unittest.TestCase):
    def _audit(self, path: Path) -> None:
        problems = audit_runbook(path.read_text(encoding="utf-8"))
        self.assertEqual(problems, [], f"{path.relative_to(REPO).as_posix()}: {problems}")

    def test_required_runbooks_are_ordered(self):
        """Reads docs/gameplan/RUNBOOK.md and RUNBOOK-TEMPLATE.md."""
        for path in REQUIRED_RUNBOOKS:
            with self.subTest(runbook=path.name):
                self.assertTrue(path.exists(), f"required runbook {path} is missing")
                self._audit(path)

    def test_optional_scratch_runbook_is_ordered_when_present(self):
        """Reads .runtime/scratch/WAVE29H-RUNBOOK.md when it exists (git-ignored)."""
        for path in OPTIONAL_RUNBOOKS:
            if not path.exists():
                self.skipTest(f"{path} not present in this checkout (git-ignored)")
            with self.subTest(runbook=path.name):
                self._audit(path)


class TemplateCarriesTheFreshValuesChecklist(unittest.TestCase):
    """The template must ship the ordered steps AND a fill-in-fresh-values checklist.

    A template with the right order but no place to record the FRESH baseline run /
    context fingerprint just re-creates the mistake one level up, so the checklist is
    part of the contract, not decoration.
    """

    TEMPLATE = REPO / "docs" / "gameplan" / "RUNBOOK-TEMPLATE.md"

    def test_template_exists_and_has_ordered_phases(self):
        self.assertTrue(self.TEMPLATE.exists(), "RUNBOOK-TEMPLATE.md is missing")
        self.assertEqual(audit_runbook(self.TEMPLATE.read_text(encoding="utf-8")), [])

    def test_template_requires_fresh_baseline_and_context_values(self):
        text = self.TEMPLATE.read_text(encoding="utf-8")
        for needle in ("FRESH_RUN", "currentContext", "现取"):
            self.assertIn(
                needle, text,
                f"template no longer requires the fresh value {needle!r} — the ordering "
                "fix is only mechanical if the template forces the executor to re-observe it")

    def test_template_states_the_refusal_is_safe(self):
        """The doctrine point: the refusal is fail-closed (called:0), a cycle not data."""
        text = self.TEMPLATE.read_text(encoding="utf-8")
        for needle in ("called", "nativeStarted"):
            self.assertIn(
                needle, text,
                f"template no longer records the fail-closed receipt fields ({needle!r}); "
                "executors must be able to tell a safe ordering refusal from a data loss")

    def test_template_triages_the_refusal_by_cause(self):
        """The remedy must not be a single one-size 're-take the baseline'.

        `actionStatus 6` has more than one cause and `levelId` is the receipt field that
        separates them; a template that names only one remedy re-creates the 2026-10-11
        misdiagnosis at the next refusal.
        """
        text = self.TEMPLATE.read_text(encoding="utf-8")
        for needle in ("actionStatus 5", "levelId", "实体集"):
            self.assertIn(
                needle, text,
                f"template no longer triages status 6 by cause ({needle!r} missing)")


class TemplateNeverFreezesABaselineRun(unittest.TestCase):
    """R2, applied to the shipped template: its `--baseline-run` must stay a placeholder."""

    TEMPLATE = REPO / "docs" / "gameplan" / "RUNBOOK-TEMPLATE.md"

    def test_every_baseline_run_value_in_the_template_is_a_placeholder(self):
        text = self.TEMPLATE.read_text(encoding="utf-8")
        concrete = [
            (lineno, value)
            for lineno, line in _code_block_lines(text)
            for value in _baseline_values(line)
            if _is_concrete(value)
        ]
        self.assertEqual(
            concrete, [],
            "the template froze a concrete --baseline-run value; it must stay a "
            "placeholder filled from the post-graph discovery, or it re-creates the "
            "exact stale-baseline bug it documents")


if __name__ == "__main__":
    unittest.main()
